// References
// [1]: Intro to the SysML v2 Language-Textual Notation.pdf

// When using Antlr4 command line tool, use the following example commands:
// antlr4 SysML2.g4 -visitor -o distj
// antlr4 -Dlanguage=Python3 SysML2.g4 -visitor -o distpy
// // Switch to distj and compile
// javac -classpath %ANTLR4_HOME%\lib\antlr-4.10.1-complete.jar; *.java
// // Run GUI
// grun SysML2 model -gui D:\GitHub\PySysML2\test_models\model_test_2.sysml2

// Language Declaration
grammar SysML2;

// A model is a set of elements that runs until the end of the file
model: element* EOF;
// An element is anything that can be a part of a model
element : namespace
        | feature
        | comment
        | doc
        | statement
        | port
        ;

// A namespace is an element with a scope defined by curly braces
namespace   : sysml2_package
            | part
            | use_case_def
            | comment
            | doc
            | port
            | connect
            ;
//------------------------------------------------------------------------------
sysml2_package: KW_PACKAGE ID '{' namespace* '}';
part_blk: (feature | comment | doc | part | port | connect | connection);
part: (part_def | part_def_specializes);
// part_def: ((KW_PART KW_DEF ID '{' part_blk* '}')|(KW_PART KW_DEF ID';'));
part_def: ((KW_PART KW_DEF? ID '{' part_blk* '}') | (KW_PART KW_DEF? ID ';'));



// e.g. part def wChip specializes 'Integrated Wireless Chip';
// e.g. part def 'Bicool Round LCD IPS Display GC9A01' specializes 'LCD Display' {}
// e.g. part def 'Raspberry Pi Pico Wireless' specializes 'Controller Board'
part_def_specializes: KW_PART KW_DEF? ID (KW_SPECIALIZES | KW_SYM_SUBSETS) ID (',' ID)*? ('{' part_blk* '}' | ';');


// Ports
port: (port_def | port_blk);
// e.g. port 'socket 1';
port_def: (KW_IN | KW_OUT)? KW_PORT ID ';' | ((KW_IN | KW_OUT)? KW_PORT ID '{' port_blk* '}');
port_blk: (feature | comment | doc );


// Use Cases [1] pg. 95
use_case_blk    : part_blk
                | objective_def
                | subject_def
                | include
                | use_case_def
                | message
                ;
use_case_def: KW_USE KW_CASE KW_DEF? ID '{' use_case_blk* '}';

// Objective Definition [1] pg. 95
part_objective_blk: doc;
objective_def: KW_OBJECTIVE '{' part_objective_blk '}';

// Subject Definition
subject_def: KW_SUBJECT ID '=' ID ';';

// Include blk
include: KW_INCLUDE ID '{' include_blk* '}';
include_blk: part_blk
             | objective_def
             | subject_def
             | message
             ;
message: (KW_MESSAGE KW_OF message_expr KW_FROM message_expr KW_TO message_expr ';')|
         (KW_MESSAGE KW_OF message_expr KW_FROM message_expr KW_TO message_expr '{' feature* '}') ;
message_expr: ID ('.' ID)*?;

// A feature is an element that is part of a namespace, e.g. package or part,
// usually defined with a semicolon ending the line
feature : feature_attribute_def
        | feature_attribute_redefines
        | feature_part_specializes
        | feature_part_specializes_subsets
        | feature_item_def
        | feature_item_ref
        | feature_actor_specializes
        ;
//------------------------------------------------------------------------------

// Connections
connection: KW_CONNECTION ID '{' connection_blk* '}';
connection_blk: (end_part | feature_attribute_def);
end_part: KW_END KW_PART ID ';';


// Connect relationships
connect: KW_CONNECT connect_expr KW_TO connect_expr ';';
connect_expr: ID ('.' ID)*?;
// connect: KW_CONNECT ID ('.' ID)? KW_TO ID ('.' ID)? ';';

// Attributes
// feature_attribute_def: KW_ATTRIBUTE ID ':' TYPE ';';
feature_attribute_def: KW_ATTRIBUTE ID ':' TYPE ';' | KW_ATTRIBUTE ID '=' CONSTANT ';';

// E.g. attribute :> 'WiFi Protocol': String = "IEEE 802.11 b/g/n wireless LAN";
// E.g. attribute redefines 'Primary Interface' = "USB 1.1";
// E.g. attribute :> 'WiFi Protocol': String = "IEEE 802.11 b/g/n wireless LAN";
feature_attribute_redefines: KW_ATTRIBUTE (KW_REDEFINES | KW_SYM_REDEFINES | KW_SYM_SUBSETS) ID (':' TYPE)? '=' CONSTANT ';';
// Part specializations and subsets
feature_part_specializes: KW_PART ID ':' ID MULTIPLICITY? (';' | '{' part_blk* '}');
feature_part_specializes_subsets: KW_PART ID ':' ID MULTIPLICITY? (KW_SUBSETS | KW_SYM_SUBSETS) ID';';
// Items, [1] pg. 17
feature_item_def: KW_ITEM ID';';
// The "ref" kw is optional. It's presented as maybe different in text, but visualized the same way
// In other words, "item driver : Person" is the same as "ref item driver : Person"
// Note that this appears to be a specialization, but the "specialize" kw doesn't work
// as it does with part redefinititons, nor the :> symbol. Super quirky!
feature_item_ref: KW_REF? KW_ITEM ID ':' ID';';
// Actors, [1] pg. 95
// Actors are (referential) part usages and so must have part definitions
feature_actor_specializes: KW_ACTOR KW_SYM_REDEFINES? ID (':' ID | '=' ID) MULTIPLICITY? ';';



// SysML2 "comments" are part of the model propper.
// Notes, on the other hand, are comments in the
// traditional sense, i.e. ignored by parser
comment : comment_unnamed
        | comment_named
        | comment_named_about
        ;
//------------------------------------------------------------------------------
// An unnamed comment, e.g.
// /* This is a comment */
comment_unnamed: COMMENT_LONG;
// A named comment, owned by element defined in, e.g.
// comment CommentName /* This is a comment */
comment_named: KW_COMMENT ID COMMENT_LONG;
// A named comment, owned by element specified in, e.g.
// comment CommentName about OwningElement /* This is a comment */
comment_named_about: KW_COMMENT KW_ABOUT ID COMMENT_LONG;

// Documentation are special comments directly owned by the element they document
doc : doc_unnamed
    | doc_named
    ;
//------------------------------------------------------------------------------
// Unamed documentation comment, owned by an element, e.g.
// doc /* This is a document */
doc_unnamed: KW_DOC COMMENT_LONG;
// Named documentation comment, owned by an element, e.g.
// doc DocName /* This is a named document */
doc_named: KW_DOC ID COMMENT_LONG;

// Statements
// Statements are lines of code that execute an action like importing a package
// A Statement can occur anywhere, even outside of a package or part. This type
// of behavior is makes a statement part of the element grammar definition.
//------------------------------------------------------------------------------
statement : import_package;
import_package: KW_IMPORT ID (KW_SYM_FQN ID)* (KW_SYM_FQN '*')? ';';


// Keywords
// Per Antrl4 "longest match" rule, keywords that contain substrings that match
// other keywords MUST be defined first. For example, 'import' must be defined
// before 'port' because 'import' contains 'port'
//------------------------------------------------------------------------------
KW_ABOUT: 'about';
KW_ACTOR: 'actor';
KW_ATTRIBUTE: 'attribute';
KW_CASE: 'case';
KW_COMMENT: 'comment';
KW_CONNECTION: 'connection'; // 'connection' before 'connect', per Antlr4 "longest match" rule
KW_CONNECT: 'connect';
KW_DEF: 'def';
KW_DOC: 'doc';
// Update
KW_FROM: 'from';
KW_END: 'end';
KW_IMPORT: 'import'; // 'import' before 'port', per Antlr4 "longest match" rule
// Include
KW_INCLUDE: 'include';
KW_ITEM: 'item';
// Update
KW_MESSAGE: 'message';
KW_OBJECTIVE: 'objective';
KW_PACKAGE: 'package';
KW_PART: 'part';
KW_PORT: 'port';
KW_REF: 'ref';
KW_REDEFINES: 'redefines';
KW_SPECIALIZES: 'specializes';
KW_SUBJECT: 'subject';
KW_SUBSETS: 'subsets';
KW_SYM_FQN: '::';
KW_SYM_REDEFINES: ':>>';
KW_SYM_SUBSETS: ':>';
KW_TO: 'to';
KW_USE: 'use';
// Update
KW_IN: 'in';
// Update
KW_OUT: 'out';
KW_OF: 'of';

// Tokens
CONSTANT: INTEGER | REAL | BOOL | STRING | NULL;
TYPE: 'Integer' | 'Real' | 'Boolean' | 'String';
ID: '\'' [ a-zA-Z_][ a-zA-Z0-9_/-]* '\'' | [a-zA-Z_][a-zA-Z0-9_/-]*;
INTEGER: [0-9]+;
REAL: [0-9]+ '.' [0-9]+;
BOOL: 'true' | 'false';
// TYPE: 'Integer' | 'Real' | 'Boolean' | 'String' | 'Type';
STRING: '"' (ESC | ~ ["\\])* '"';
//STRING2: '\'' (ESC | ~ ["\\])* '\'';
MULTIPLICITY: '[' INTEGER '..' INTEGER ']';
fragment ESC: '\\' (["\\/bfnrt] | UNICODE);
fragment UNICODE: 'u' HEX HEX HEX HEX;
fragment HEX: [0-9a-fA-F];
NULL: 'null';
WS: [ \t\r\n]+ -> skip;
// Notes are special comments that are ignored and not part of the model
//------------------------------------------------------------------------------
NOTE: '//' ~[\r\n]* -> skip;
COMMENT_LONG: '/*'.*?'*/';
