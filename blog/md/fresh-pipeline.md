# Rendering Pipeline in Fresh Text Editor
    
The source file is text on disk, in UTF-8 format.

A piece tree data structure represents this file. Some of the data may be in memory while the rest is pointed at the disk. The piece tree provides an iterator that walks in linear offset order over nodes of the tree, each pointing at chunks of the data. It also provides indexing of the line numbers so it's relatively cheap to find an offset given a line number (or vice versa). For large files, we don't do this indexing to avoid loading the entire file.

The piece tree doesn't actually store any data. It contains information about where the data is stored, by holding an index into an array of StringBuffers. A StringBuffer contains the memory itself (if loaded into RAM) or offset in the backing file (if not loaded into RAM). Modified / inserted bytes are stored in StringBuffers that can grow in size. This allows to reduce memory allocations by writing edits consequetively per edited region (in theory we could make it a single linear memory region but Fresh doesn't currently do that).

The piece tree and its accompanying StringBuffer vector are maintained by TextBuffer, a struct representing a file being displayed or edited (also tracks line ending format LF/CRLF, version counter for LSP, various flags like read only, large file, etc.) The piece tree by itself never loads data or even knows how to access the data, it accepts information from its caller and is a clean data structure decoupled from IO.

TextBuffers provide a LineIterator which starts at some offset and iterates over lines by iterating over piece tree nodes and lazily loading chunks as it proceeds. It's used below during the rendering process. The lazy loading populates pieces of the TextBuffer from disk so that repeated iteration reuses the loaded data.

Each text buffer can have zero or more viewports. The TextBuffer state is shared by all viewports. Each viewport represents a (possibly visible or hidden) tab in a split view on the screen. Viewports have their own separate state: cursors, scroll state, selections, etc. basically anything that we'd want to store per view rather than per underlying buffer.

To render a viewport, we start at the top offset (maintained as an absolute byte offset) of the view and iterate over lines in the underlying buffer until we fill up the view area. Unfortunately, text does not map cleanly to screen positions. We need to incoporate styles, highlighting, variable width characters (such as tabs), decorations like LSP inlay hints (type hints) and allow plugins to insert 'virtual text' (such as git blame headers or diff filler lines). To support all these, the flow I've ended up using is:
    
1. Input source text
2. Tokenizer
3. View Transformer (plugins)
4. Virtual line mapping
5. Inject virtual lines
6. Syntax highlighting + reference highlighting

*Tokenizer*: The tokenization converts raw input bytes into tokens: LF / CRLF to line break tokens, spaces or tabs into dedicated whitespace tokens, binary (non-text) bytes as binary tokens, and collects contiguous blocks of anything else as text tokens. Part of this process is to handle edge cases such as very long lines (think huge 1GB json file as a single line) by breaking them with line break tokens if line length exceeds some threshold - this is neccessary to cap the number of bytes needed for filling up the view.

The viewport has room for a known number of lines. When processing input at the start of the pipeline we plan to fill up the number of lines in the viewport, but further along the pipeline we could end up stopping early - for example if line wrapping is enabled or if a plugin injects virtual lines or other decorations that use up vertical space.

*View transformer* is a way for plugins to arbitrarily change the stream of tokens (for example by transforming content),

*Virtual line mapping* is the process of creating a bi-directional map: source byte offset <-> visual column offset. Both directions of this mapping are needed: when we move the cursor, the movement is visual (one column to the left or right, or up into the same column in the previous line, etc.) so we need a way to know where in the source bytes each visual location maps to. In the other direction (byte offset -> visual column), we need it because... we don't actually use that. 

*Inject virtual lines* allows plugins to inject entire lines before some offset. This is supposed to be reliable even under edits by using the marker (interval tree) system.

*Syntax higlighting* is currently re-calculated for every frame, but only using a subset of the full file (current viewport plus some large window of preceding text for syntax context). This is done using syntect which provides highlighting using Textmate-based grammars.

*Reference highlighting* is the feature of showing a highlight over a symbol or word in the text where the cursor is positioned and also all other occurances of the word that are visible in the viewport. This is implemented by registering overlays in the interval tree. If the user edits the buffer, the overlays automatically stay correct, ensuring the highlighting doesn't drift during edits. This way the reference highlight overlays are only invalidated and re-created if the cursor moves to a different word, not on every render frame nor on scrolling etc.



