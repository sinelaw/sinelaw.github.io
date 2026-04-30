# Rendering Pipeline in Fresh Text Editor

The source file is text on disk, in UTF-8 format.

## Storage/Memory Layer: The Piece Tree

A **piece tree** data structure represents this file. Some of the data may be in memory while the rest is pointed at the disk. The piece tree support a line-number index so it's relatively cheap to find an offset given a line number, or the other way around - find the byte-offset of a given line number (which is important for "go to line" features). For large files, we don't do this indexing automatically to avoid loading the entire file. We can index the lines on request (if the user wants "go to line") by streaming through the file without loading it all into memory at once. The streaming indexing also supports remote files (indexing without fetching the entire file over the network).

The piece tree itself doesn't actually store any data. It contains information about where the data is stored, by holding an index into an array of StringBuffers. A StringBuffer contains the memory itself (if loaded into RAM) or offset in the backing file (if not loaded into RAM). Modified / inserted bytes are stored in StringBuffers that can grow in size. This allows to reduce memory allocations by writing edits consequetively per edited region (in theory we could make it a single linear memory region but Fresh doesn't currently do that).

A simplified version of the code might look like this - the actual code is similar:

```rust
pub enum StringBuffer {
    Loaded {
        data: Vec<u8>,
        line_starts: Option<Vec<usize>>, // positions of newlines
        file_offset: Option<usize>, // if loaded from disk and unmodified
    },
    Unloaded {
        file_offset: usize,
        bytes: usize,
    },
}
```

A single StringBuffer may serve more than one node in the piece tree. The nodes point into an offset within the StringBuffer.

```rust
enum PieceTreeNode {
    Internal {
        left_bytes: usize,      // Total bytes in left subtree
        lf_left: Option<usize>, // Total newlines in left subtree
        left: Arc<PieceTreeNode>,
        right: Arc<PieceTreeNode>,
    },
    Leaf {
        location: BufferLocation,
        offset: usize,                // Offset within the buffer
        bytes: usize,                 // Number of bytes in this piece
        line_feed_cnt: Option<usize>, // Number of line feeds in this piece
    },
}
```

The tree structure is what enables efficient lookup & insertion: given a byte offset, we walk down the left/right nodes to reach the `Leaf` that contains the desired data. Inserts and edits are managed by splitting nodes. The tree can be rebalanced to minimize the depth.

The API includes things like:
- `insert`, which inserts bytes by walking from the root down to the leaf where the bytes belong, splits that leaf, and updates all the ancestors back up to the root.
- `offset_to_position` which converts a byte offset to a line number + column number.
- `position_to_offset` which converts a line number + column number to byte offset, and `line_range` which converts line number to byte offset start/end range. Both of these work by walking the tree's nodes by line index instead of by byte offset.
- Iterators from a given offset, etc.

### Efficient Tree Diffs

Having a piece tree made it easy to implement a few features, like fault recovery - we can save only the non-file-backed buffers to disk which is fast even for huge files. Also diffing the in-memory buffer against the disk / finding modified regions for gutter markers is fast, we look for non-file-back nodes and then compare only those regions to the disk version.

So imagine we want to iterate all unsaved regions in a buffer - pieces of data that were inserted or modified by the user but not yet saved to disk. We can walk the entire tree structure and find leaf nodes that point to StringBuffers that have modifications, but this will be slow if the tree is large. To speed things up, we store another copy of the tree - "the pristine tree" as it was when loaded from disk (this is called `saved_root` in the Fresh source code). We can then walk the two trees in tandem and whenever we hit a branch (`Internal`) node that has the exact same left or right branch, we can completely skip those branches and avoid iterating further down. In Fresh this is called a "structural diff". Note that tree *structure* even when the data itself is unchanged: when just loading chunks of data from disk, we update the tree nodes to point at the loaded data in that region instead of pointing at the disk. So to make the structural diff possible, we need to keep the pristine tree structure in sync with data loading operations (non-edits, where we splice in a part of the tree to point to a memory-loaded buffer instead of just saying it's on disk). This means that the pristine reference tree is mutated (replaced, actually) every time we load data from disk to memory and update the tree, just as the actual "working" tree is mutated.

Furthermore, the structure may still not match 100% in regions where we modified data. A node could have been split and data edited, but the end result could be that the data in memory is actually identical to the one on disk. So to completement the structural diff we also compare byte-by-byte regions of the tree which don't match. There's a choice here - for some use cases we could just say that structure mismatches are treated as an real difference (even if the bytes are identical), for example for dumping recovery data we can just dump the region of data even if it *may* be unmodified. For other features like showing accurate diff indicators on the gutter, we would still want to compare the region, byte-by-byte.

### Testing Piece Tree

I'm paranoid about having a data loss or corruption bug, as I should. To sleep better at night I use property testing on the piece tree. These tests generate a set of randomized operations, apply them to the tree, and check that certain invariants are always true. Here are some of them:

- Total byte count as reported by the tree is the same as all the sum of all insert/delete operations.
- Tree is balanced, to at most some level of imbalance.
- Insert followed by delete in the same range equals the original data.
- Sum of all piece lengths = total tree length, and same for line numbers

At a higher level I have tests that perform a workload on a tree and an identical on a simple array, and then compares byte-by-byte the final contents as reported by the tree vs. the simple arrary. After all the splitting, balancing, node-iterating and data merging inside the tree shouldn't make a different for the end result and the two should be equal. This shows that our tree is nothing more than an optimization.

All these tests are executed as property tests - the operations are generated and arbitrary, not just a single scenario or a handful of specific scenarios.

## TextBuffer, the virtual "buffer" layer

The piece tree and its accompanying StringBuffer vector are maintained by TextBuffer, a struct representing a file being displayed or edited (also tracks line ending format LF/CRLF, version counter for LSP, various flags like read only, large file, etc.) The piece tree by itself never loads data, it accepts information from its caller and is a clean data structure decoupled from IO. The TextBuffer ties the IO side-effects with the piece tree, making it easier to test the tree in isolated memory-only property tests.

TextBuffers provide a LineIterator which starts at some offset and iterates over lines by iterating over piece tree nodes and lazily loading chunks as it proceeds. It's used below during the rendering process. The lazy loading populates pieces of the TextBuffer from disk so that repeated iteration reuses the loaded data.

Each text buffer can have zero or more viewports. The TextBuffer state is shared by all viewports. Each viewport represents a (possibly visible or hidden) tab in a split view on the screen. Viewports have their own separate state: cursors, scroll state, selections, etc. basically anything we'd want to store per view rather than per underlying buffer.

As explained below, there are many features that require annotating pieces of the text with some metadata (such as highlighting). These are called markers. Since the text is being edited, the markers are not static - they don't stay in their original offset. To avoid re-calculating highlighting, selection regions, etc. on every single keypress, in Fresh we use an **interval tree** to maintain the marker information. The interval tree provides an API for inserting markers by position, and then later efficiently querying their position by ID (efficiently). Between insert and query you can also feed edits like insertions or text removals, into the interval tree, which efficiently shifts the positions of all affected markers. *Overlays* are built on top of the marker interval tree, and pair start/end markers to represent self-adjusting ranges.

To render a viewport, start at the top offset (maintained as an absolute byte offset) of the view and iterate over lines in the underlying buffer until filling up the view area. Unfortunately, text does not map cleanly to screen positions. We need to incoporate styles, highlighting, variable width characters (such as tabs), decorations like LSP inlay hints (type hints) and allow plugins to insert 'virtual text' (such as git blame headers or diff filler lines). To support all these, the flow I've ended up using is:

1. Input source text
2. Tokenizer (Base tokens)
3. View Transformer (Plugins / Virtual Text)
4. Wrapping (Line breaks for width limits)
5. Line Generation (ViewLines)
6. Styling & Rendering (Syntax/Semantic highlighting, Overlays, Selection, Cursor)

*Tokenizer*: The tokenization converts raw input bytes into tokens: LF / CRLF to line break tokens, spaces or tabs into dedicated whitespace tokens, binary (non-text) bytes as binary tokens, and collects contiguous blocks of anything else as text tokens.

*Wrapping*: After tokenization and transformations, edge cases are handled - such as very long lines (think huge 1GB json file as a single line) by inserting line break tokens if line length exceeds a safety threshold (or the viewport width if soft wrapping is enabled).

The viewport has room for a known number of lines, but the pipeline can't know in advance how many visual rows it will produce. For example if line wrapping is enabled or if a plugin injects virtual lines or other decorations that use up vertical space.

*View transformer* is a way for plugins to arbitrarily change the stream of tokens (for example by transforming content or injecting virtual text like headers). I'm not sure I need it - the idea was to allow plugins to completely rewrite the token stream that gets rendered. All the use cases I had in mind are better served by other mechanisms: markdown preview, for example, uses "omit" overlays tied to specific positions in the stream, to remove markup. It's also a problematic concept to have - arbitrary plugin-dictated transformation of the view. For one, caching would break unless the plugin transformation is pure (output only depends on the input). I think I might remove the view transformer.

*Line Generation* creates the `ViewLine` structures which contain the bi-directional map: source byte offset <-> visual column offset. Both directions of this mapping are needed: when we move the cursor, the movement is visual so we need to know where in the source bytes each visual location maps to. In the other direction (byte offset -> visual column), we use it to calculate cursor screen positions and handle horizontal scrolling.

For the many different highlights and indicators we extract at the start of the render flow the set of markers that apply to our current viewport range. We store these overlays in an array sorted by position and later reference it while rendering. I'm not sure if that's the best approach but it's to avoid multiple O(log n) lookups per each offset in the viewport.

*Syntax higlighting* is currently re-calculated for every frame, but only using a subset of the full file (current viewport plus some large window of preceding text for syntax context). This is done using syntect which provides highlighting using Textmate-based grammars.

*Reference highlighting* is the feature of showing a highlight over a symbol or word in the text where the cursor is positioned and also all other occurances of the word that are visible in the viewport. This is implemented by registering overlays in the interval tree. If the user edits the buffer, the overlays automatically stay correct, ensuring the highlighting doesn't drift during edits. This way the reference highlight overlays are only invalidated and re-created if the cursor moves to a different word, not on every render frame nor on scrolling etc.

*Semantic highlighting* is an LSP feature - we ask the LSP server to provide highlighting tokens, these get translated to overlays (again, to automatically move with edits efficiently). There are two APIs: full, and range. Full gets the semantic highlighting tokens for the entire document. Range is used for the current viewport only. Full also supports "delta" API where the LSP server only reports what has changed (based on didChange events sent from Fresh to the LSP).
