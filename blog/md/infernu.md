# Revisiting Infernu's Type System - a Safe Subset of JavaScript

Back in 2015 - already 10 years ago - I built [Infernu](https://github.com/sinelaw/infernu), an experimental project to create static type checking, with type inference, for JavaScript. I started working on it before TypeScript was announced. The project was born from my frustrations while working on frontend code. As soon as I stopped working on frontend I essentially abandonded this effort to focus on other things.

I never documented the type system in a clear and concise way, so I decided to give it a shot.

## Introduction

Infernu employs a polymorphic, structural type system based on Hindley-Milner type inference. It features full type inference, parametric polymorphism, row-polymorphism for structural typing, and simple type classes. The system is designed to statically type check a subset of JavaScript without requiring explicit type annotations.

## Types

The following are the main types in the system:

- **Primitive Types**: `Number`, `String`, `Boolean`, `Regex`, `Undefined`, `Null`, `Date`.
- **Type Variables**: `a, b, ...` which can be flexible (un-instantiated) or skolem (rigid).
- **Function Types**: `(T1, T2, ...) -> T_result`, where `T1`, `T2`, etc. are argument types and `T_result` is the return type.
- **Row Types**: `{l1: T1, l2: T2, ..., l_n: T_n | r}` represent objects with properties `l_i` of type `T_i`. `r` is a row variable, making the row open for extension. A closed row has no row variable.
- **Type Constructors**: `[T]` for an array of type `T`, and `Map T` for a map from strings to values of type `T`.
- **Qualified Types**: `C a => T` is a type `T` constrained by a predicate `C a`, where `C` is a type class and `a` is a type variable.
- **Type Schemes**: `forall a_1, ..., a_n. T` is a polymorphic type, where `T` is a qualified type with universally quantified type variables `a_i`.

## Typing Judgments

The core of the type system is the typing judgment, which has the form:

`Γ ⊢ e : τ`

This is read as: "In the type environment `Γ`, the expression `e` has the type `τ`". `Γ` is a mapping from variable names to type schemes.

### Literals

`Γ ⊢ lit : τ` where `τ` is the type of the literal.

- `Γ ⊢ n : Number` (for a number literal `n`)
- `Γ ⊢ s : String` (for a string literal `s`)
- etc. for other literals.

### Variables

`Γ(x) = forall a_1, ..., a_n. τ`
`b_1, ..., b_n` are fresh type variables
`τ' = τ[a_1 := b_1, ..., a_n := b_n]`
-----------------------------------------
`Γ ⊢ x : τ'`

If a variable `x` is in the environment with a polymorphic type, it is instantiated with fresh type variables.

### Abstraction (Function Definition)

`Γ, x_1:τ_1, ..., x_n:τ_n ⊢ e : τ`
-----------------------------------------------
`Γ ⊢ (x_1, ..., x_n) => e : (τ_1, ..., τ_n) -> τ`

A function is typed by adding its arguments with fresh type variables to the environment and inferring the type of its body.

### Application (Function Call)

`Γ ⊢ e_f : (τ_1, ..., τ_n) -> τ_r`
`Γ ⊢ e_1 : τ'_1`
...
`Γ ⊢ e_n : τ'_n`
`unify(τ_1, τ'_1)`
...
`unify(τ_n, τ'_n)`
------------------------------------------------
`Γ ⊢ e_f(e_1, ..., e_n) : τ_r`

The type of a function application is the return type of the function, after unifying the function's argument types with the types of the supplied arguments.

### Let Expressions

`Γ ⊢ e1 : τ1`
`Γ' = generalize(Γ, τ1)`
`Γ, x:Γ' ⊢ e2 : τ2`
------------------------
`Γ ⊢ let x = e1 in e2 : τ2`

A `let` expression is typed by inferring the type of the bound expression, generalizing it to a type scheme, adding it to the environment, and then inferring the type of the body.

### Object Literals (Rows)

`Γ ⊢ e_1 : τ_1`
...
`Γ ⊢ e_n : τ_n`
-------------------------------------------------
`Γ ⊢ {l_1: e_1, ..., l_n: e_n} : {l_1:τ_1, ..., l_n:τ_n}`

The type of an object literal is a closed row type with the types of its properties.

### Property Access

`Γ ⊢ e : {..., l:τ, ... | r}`
--------------------------
`Γ ⊢ e.l : τ`

The type of a property access is the type of the property in the row type of the object.

### Property Assignment

`Γ ⊢ e_obj : {..., l:τ, ... | r}`
`Γ ⊢ e_val : τ'`
`unify(τ, τ')`
`value_restriction(τ')`
--------------------------------
`Γ ⊢ e_obj.l = e_val : τ'`

Property assignment unifies the type of the property with the type of the value. The value's type is restricted to be monomorphic (the "value restriction").

## Recursive Types

Infernu supports equi-recursive types, where two types are considered equivalent if their infinite unfoldings are identical. Recursive types are not created explicitly, but are inferred by the type system when a type variable is unified with a type that contains it.

For example, in the expression `let x = { a: x }`, the type of `x` is inferred to be a recursive type `μa. { a: a }`. This is represented internally by creating a named type and substituting the recursive occurrence of the type variable with the named type.

The judgment for this is:

`Γ, x:α ⊢ e : τ`
`unify(α, τ)` results in an occurs check failure for `α` in `τ`
-----------------------------------------------------------------
`Γ ⊢ let x = e in ... : μa.τ[x:=a]`

Recursive types are essential for correctly typing many common JavaScript patterns, such as self-referential objects and certain functional programming idioms. They are also crucial for modeling object-oriented methods that use `this`. When an object has a method that refers to the object itself (e.g., `this.method()`), the object's type is inherently recursive. The recursive type captures this self-referential nature, allowing `this` to be correctly typed within the method's context as referring to an instance of the encompassing recursive type.

## Type Classes

Type classes constrain polymorphic types.

- **`Plus a`**: For types that support the `+` operator.
  - Instances: `Number`, `String`.

- **`Indexable c i e`**: For container types.
  - `c`: container type
  - `i`: index type
  - `e`: element type
  - Instances:
    - `Indexable [a] Number a` (Arrays)
    - `Indexable (Map a) String a` (String Maps)
    - `Indexable String Number String` (Strings)

A judgment with a type class constraint is written as:

`Plus a => Γ ⊢ e : (a, a) -> a`

This means that `e` is a function that takes two arguments of the same type `a` and returns a value of type `a`, where `a` must be an instance of the `Plus` type class.

## JavaScript Idioms and Exclusions

Infernu's type system is designed to support many common JavaScript idioms while ensuring type safety.

### Supported Idioms

- **Object-Oriented Programming**:
  - **`this` keyword**: The type of `this` is inferred and correctly handled, even with its dynamic scoping rules.
  - **`new` keyword**: Constructor functions are supported. The type of a `new` expression is the type of `this` within the constructor.
  - **Methods**: Methods are properties of row types that have function types. Polymorphic methods are supported via rank-2 types for rows.
  - **Methods with `this` and Recursive Types**:
    Infernu accurately models methods that operate on their own object (`this`) using recursive types.
    Consider the following JavaScript example:
    ```javascript
    let counter = {
      count: 0,
      inc: function() {
        this.count = this.count + 1;
      }
    };
    ```
    For the `counter` object:
    *   **`count` Field Type**: `Number` due to the explicit initialization to `0`.
    *   **`inc` Method Type (within the object context)**: `(self) -> Undefined`, assuming `self` will be the full object type, which we haven't yet defined. The method implicitly receives `self` as its `this` argument.
    *   **`counter` Object Type**: Has type `self` as we declared above, which equals a row with the field and method: `{ count: Number, inc: (self) -> Undefined }`. Since that expanded type refers to `self`, we have a **recursive type**: `μself. { count: Number, inc: (self) -> Undefined }`.
    This example demonstrates how Infernu uses recursive types to accurately model methods that operate on their own object (`this`), ensuring that the type of `this` is correctly understood as the type of the object itself.
  - **Prototypal Inheritance**: While not directly modeled, inheritance can be simulated through object composition and row polymorphism.

- **Functional Programming**:
  - **Higher-Order Functions**: Functions as first-class citizens are naturally supported.
  - **Closures**: The type system correctly infers the types of variables in closures.

- **Structural Typing**:
  - Row polymorphism allows for "duck typing" in a statically typed way. A function that expects an object with a certain property can be called with any object that has that property, regardless of its other properties.

### Excluded Code

To ensure static type safety, Infernu excludes some of JavaScript's more dynamic and unsafe features:

- **Implicit Type Coercion**: Expressions like `3 + 'a'` are disallowed. The `Plus` type class requires both operands to be of the same type (either `Number` or `String`).
- **`eval()`**: Dynamic code evaluation is not supported.
- **Arbitrary Monkey-Patching**: While adding properties to objects is possible with open row types, modifying the type of an existing property is restricted.
- **Heterogeneous Arrays**: Arrays in Infernu must be homogeneous, meaning all elements must have the same type. JavaScript's ability to mix types in an array, like `[1, "hello", true]`, is not permitted.
- **`arguments` object**: The `arguments` object is not supported. All function arguments must be explicitly declared.

## A note about TypeScript

TypeScript is commonly described as a **superset of JavaScript** in that any valid JavaScript code is theoretically also valid TypeScript. That's not exactly true because code that violates TypeScript's static typing rules triggers errors (depending on configuration), so there are many valid JavaScript programs which are not valid TypeScript programs. That being said TypeScript focuses on gradual typing and improved idioms and doesn't make as strong a statement about what parts of JavaScript are strictly excluded.


