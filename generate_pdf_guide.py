"""Generate a PDF guide for the faculty review and project demonstration."""

import os
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether, HRFlowable
)
from reportlab.pdfgen import canvas


class NumberedCanvas(canvas.Canvas):
    """Two-pass canvas to dynamically compute and draw 'Page X of Y' footers."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#64748B"))
        
        # Header (pages > 1)
        if self._pageNumber > 1:
            self.drawString(36, 762, "LLM-Assisted Compiler Error Diagnosis & Repair Tool — Faculty Review Guide")
            self.setStrokeColor(colors.HexColor("#E2E8F0"))
            self.setLineWidth(0.5)
            self.line(36, 756, 576, 756)

        # Footer (all pages)
        self.setStrokeColor(colors.HexColor("#E2E8F0"))
        self.setLineWidth(0.5)
        self.line(36, 42, 576, 42)
        
        self.drawString(36, 30, "BCSE307L Compiler Design | Student: Namish (3rd Year CSE)")
        page_str = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(576, 30, page_str)
        self.restoreState()


def create_pdf(output_filename="Faculty_Review_Demo_Guide.pdf"):
    doc = SimpleDocTemplate(
        output_filename,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=46,
        bottomMargin=48
    )

    styles = getSampleStyleSheet()

    # Custom Palette
    c_primary = colors.HexColor("#0F172A")    # Deep Navy / Slate 900
    c_accent = colors.HexColor("#1D4ED8")     # Blue 700
    c_dark = colors.HexColor("#1E293B")       # Slate 800
    c_code_bg = colors.HexColor("#F8FAFC")    # Slate 50
    c_border = colors.HexColor("#CBD5E1")     # Slate 300
    c_talk_bg = colors.HexColor("#EFF6FF")    # Blue 50
    c_talk_bar = colors.HexColor("#3B82F6")   # Blue 500

    # Custom Paragraph Styles
    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        textColor=c_primary,
        spaceAfter=4,
    )
    subtitle_style = ParagraphStyle(
        "DocSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10.5,
        leading=14,
        textColor=c_accent,
        spaceAfter=10,
    )
    meta_style = ParagraphStyle(
        "DocMeta",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor("#475569"),
    )
    h1_style = ParagraphStyle(
        "H1",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=12.5,
        leading=16,
        textColor=c_primary,
        spaceBefore=10,
        spaceAfter=4,
    )
    h2_style = ParagraphStyle(
        "H2",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=13,
        textColor=c_accent,
        spaceBefore=6,
        spaceAfter=2,
    )
    body_style = ParagraphStyle(
        "Body",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.8,
        leading=12,
        textColor=c_dark,
        spaceAfter=3,
    )
    cmd_style = ParagraphStyle(
        "CmdText",
        parent=styles["Normal"],
        fontName="Courier-Bold",
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#0F172A"),
    )
    talk_style = ParagraphStyle(
        "TalkText",
        parent=styles["Normal"],
        fontName="Helvetica-Oblique",
        fontSize=8.5,
        leading=11.5,
        textColor=colors.HexColor("#1E3A8A"),
    )
    bullet_style = ParagraphStyle(
        "Bullet",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=11.5,
        textColor=c_dark,
        leftIndent=12,
        spaceAfter=1.5,
    )
    table_cell = ParagraphStyle(
        "TableCell",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=10.5,
        textColor=c_dark,
    )
    table_cell_bold = ParagraphStyle(
        "TableCellBold",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10.5,
        textColor=c_primary,
    )
    table_cell_cmd = ParagraphStyle(
        "TableCellCmd",
        parent=styles["Normal"],
        fontName="Courier-Bold",
        fontSize=7.5,
        leading=9.5,
        textColor=colors.HexColor("#1D4ED8"),
    )

    story = []

    # Title & Metadata Header Block
    header_table = Table(
        [
            [
                Paragraph("<b>LLM-Assisted Compiler Error Diagnosis & Repair Tool</b>", title_style),
                Paragraph("<b>Project Review Guide</b><br/>BCSE307L — Compiler Design", meta_style),
            ],
            [
                Paragraph("Step-by-Step Terminal Commands, Architecture Highlights & Faculty Talking Points", subtitle_style),
                Paragraph("<b>Student:</b> Namish (3rd Year CSE)<br/><b>Stack:</b> Python, Automata, AST, Groq Cloud API", meta_style),
            ]
        ],
        colWidths=[370, 170]
    )
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
        ('TOPPADDING', (0, 0), (-1, -1), 1),
    ]))
    story.append(header_table)
    story.append(HRFlowable(width="100%", thickness=1.5, color=c_accent, spaceBefore=4, spaceAfter=8))

    # Section 1: Executive Summary & Novelty
    story.append(Paragraph("1. Executive Summary & Core Novelty", h1_style))
    summary_text = (
        "<b>Core Research Hypothesis:</b> Existing LLM-assisted repair systems (e.g., wrappers around GCC or Clang) "
        "treat compilers as black boxes by scraping flattened <code>stderr</code> text strings after syntactic and semantic "
        "structure has been lost. This project implements a custom C-subset compiler front-end where every error is modeled "
        "as an enriched, typed <b>Diagnostic</b> object directly at the moment of failure. These diagnostics carry live grammar "
        "rule stack paths, delimiter opener references, and scoped symbol table snapshots into <b>error-type-specific prompt templates</b>, "
        "which are dispatched to <b>Groq Cloud API</b> (e.g., <code>openai/gpt-oss-120b</code>, <code>llama-3.1-8b</code>) and compiled "
        "in memory through an <b>automated fix verification layer</b>."
    )
    story.append(Paragraph(summary_text, body_style))
    story.append(Spacer(1, 4))

    # Helper function for rendering a command block
    def make_step(step_num, title, cmd, what_it_does, key_concepts, talking_point):
        items = []
        items.append(Paragraph(f"<b>Step {step_num}: {title}</b>", h2_style))
        
        # Command Box
        cmd_p = Paragraph(f"<b>$</b> {cmd}", cmd_style)
        cmd_box = Table([[cmd_p]], colWidths=[540])
        cmd_box.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), c_code_bg),
            ('BOX', (0, 0), (-1, -1), 0.75, c_border),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        items.append(cmd_box)
        items.append(Spacer(1, 3))

        # Explanation
        items.append(Paragraph(f"<b>What this command executes:</b> {what_it_does}", body_style))
        items.append(Paragraph(f"<b>Compiler internals demonstrated:</b> {key_concepts}", body_style))

        # Talking Point Box
        talk_p = Paragraph(f"<b>What to say to faculty:</b> \"{talking_point}\"", talk_style)
        talk_box = Table([[talk_p]], colWidths=[540])
        talk_box.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), c_talk_bg),
            ('LINELEFT', (0, 0), (0, 0), 3, c_talk_bar),
            ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor("#BFDBFE")),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        items.append(talk_box)
        items.append(Spacer(1, 5))
        return KeepTogether(items)

    story.append(Paragraph("2. Step-by-Step Review Demonstration Script", h1_style))

    # Step 1
    story.append(make_step(
        step_num=1,
        title="Comprehensive Test Suite Verification (76/76 Passing)",
        cmd="python -m unittest discover -s tests -v",
        what_it_does="Discovers and runs all 76 unit tests across automata minimization, lexer error recovery, recursive-descent precedence, semantic type checking, Groq/LLM integration, fix verification, and evaluation.",
        key_concepts="Automated test harness, regression testing, full pipeline verification (100% test pass rate across 76 tests).",
        talking_point="We verified our compiler front-end with 76 unit tests built from first principles. Every phase—from regex DFA construction to panic-mode recovery, semantic scope checking, and Groq LLM integration—is covered with zero failing tests."
    ))

    # Step 2
    story.append(make_step(
        step_num=2,
        title="Automata Theory: Thompson's NFA to Minimal DFA",
        cmd=".\\toycompiler.bat dfa-stats",
        what_it_does="Compiles the formal lexical specification into an ε-NFA, determinizes it into a DFA, and applies Moore's partition refinement to minimize states, printing state, accepting, and transition metrics.",
        key_concepts="Regex AST parsing, Thompson's Construction, Subset Construction (ε-closure), Moore's Partition Minimization (67 states, 62 accepting, 2,730 transitions).",
        talking_point="Instead of using standard high-level regex libraries, our lexer compiles token specifications using classic automata theory. It transforms regular expressions into an ε-NFA, converts them via subset construction, and minimizes the DFA to an optimal 67 states."
    ))

    # Step 3
    story.append(make_step(
        step_num=3,
        title="Recursive-Descent Parser, AST & Scoped Symbol Table",
        cmd=".\\toycompiler.bat run examples\\valid_factorial.toy --ast --symbols",
        what_it_does="Tokenizes and parses a complete Toy-C program with recursion, loops, and boolean logic; renders an ASCII Abstract Syntax Tree and prints the scoped symbol table tree.",
        key_concepts="Explicit operator precedence hierarchy (assignment → or → and → equality → comparison → term → factor → unary → call → primary); nested lexical scopes (global, function, block).",
        talking_point="Our parser implements recursive-descent with explicit grammar layering to enforce operator precedence without ambiguity. The semantic analyzer walks the AST and builds a hierarchical scope tree tracking variable names, types, and function signatures."
    ))

    # Page Break to start Page 2 cleanly with Error Recovery and LLM Repair
    story.append(PageBreak())

    # Step 4
    story.append(make_step(
        step_num=4,
        title="Panic-Mode Multi-Error Recovery & Rule Stack Tracing",
        cmd=".\\toycompiler.bat run examples\\err_multiple.toy",
        what_it_does="Parses a file containing multiple syntax errors in different declarations; recovers at statement and declaration boundaries (';', '}', keywords) to diagnose all errors in a single pass.",
        key_concepts="Panic-mode recovery, synchronization tokens, live grammar rule stack tracking attached to Diagnostic objects.",
        talking_point="Rather than aborting on the first syntax error, Toy-C implements panic-mode synchronization. It recovers at delimiter and statement boundaries so students receive a comprehensive diagnostic report in a single compilation run."
    ))

    # Step 5
    story.append(make_step(
        step_num=5,
        title="Error-Type-Specific Prompting & Verified Repair (Syntax Error)",
        cmd=".\\toycompiler.bat diagnose examples\\err_missing_semicolon.toy --online",
        what_it_does="Extracts the error context (source window, insertion caret, rule stack), dispatches the specialized 'PromptSyntaxMissingDelimiter' template, queries Groq Cloud API for structured JSON diagnosis, recompiles the suggested patch in memory, and prints a verified diff.",
        key_concepts="Structured Diagnostic → Context Extraction → Typed Prompt Template → Live Groq Inference (openai/gpt-oss-120b) → In-Memory Recompilation → [VERIFIED FIX] badge.",
        talking_point="Here is our core novelty: the diagnostic knows the exact insertion point where ';' was expected. It dispatches the specialized PromptSyntaxMissingDelimiter template to Groq's high-speed cloud inference. Once the LLM suggests a fix, our verification layer recompiles the code in memory to guarantee the fix works before showing it to the student."
    ))

    # Step 6
    story.append(make_step(
        step_num=6,
        title="Semantic Typo Diagnosis with In-Scope Symbol Snapshot",
        cmd=".\\toycompiler.bat diagnose examples\\benchmarks\\12_sem_var_typo.toy --online",
        what_it_does="Diagnoses an undeclared variable caused by a typo ('conter' instead of 'counter'); dispatches 'PromptUndeclaredVariable' with active in-scope symbols; queries Groq and verifies the clean recompilation.",
        key_concepts="Scope traversal, difflib spelling recommendations, in-scope symbol table slice injection into LLM prompt context.",
        talking_point="For semantic errors like undeclared variables, our compiler captures a snapshot of all active symbols in scope. The prompt template passes this symbol table slice to Groq along with spelling distance metrics, allowing the LLM to fix typos with 100% precision."
    ))

    # Page Break to start Page 3 cleanly with JSON export, Evaluation & Summary Cheat Sheet
    story.append(PageBreak())

    # Step 7
    story.append(make_step(
        step_num=7,
        title="Machine-Readable Structured JSON Diagnostic Output",
        cmd=".\\toycompiler.bat run examples\\benchmarks\\12_sem_var_typo.toy --json",
        what_it_does="Emits the complete compiler diagnostic as machine-readable JSON, showing error category, code, rule stack, source snippet, expected/found tokens, details, and visible symbols.",
        key_concepts="Rich Diagnostic schema: code, category, location, rule_stack, details, symbols, hint, related locations.",
        talking_point="Notice that our error representation is structured data from the exact moment of failure. There is zero fragile text parsing or stderr scraping; downstream agents and prompt templates receive full compiler context."
    ))

    # Step 8
    story.append(make_step(
        step_num=8,
        title="Comparative Evaluation Suite & Ablation Study",
        cmd=".\\toycompiler.bat eval --output evaluation_report.md --json",
        what_it_does="Executes a 20-program benchmark suite; runs Evaluation 1 (Toy-C structured context vs. raw GCC/Clang stderr) and Evaluation 2 (typed prompt dispatching vs. generic single-prompt baseline); generates a Markdown report.",
        key_concepts="Empirical evaluation, ablation study, rubric scoring (novice readability, grounding, actionability), fix verification rate.",
        talking_point="To validate our contribution scientifically, we curated 20 benchmark programs across syntax, lexical, and semantic error classes. Our ablation study proves that error-type-specific prompting combined with in-memory recompilation achieves a 100% clean fix rate."
    ))

    # Section 3: Summary Table
    story.append(Spacer(1, 4))
    story.append(Paragraph("3. Quick-Reference Review Cheat Sheet", h1_style))
    
    table_data = [
        [
            Paragraph("<b>Step</b>", table_cell_bold),
            Paragraph("<b>Command</b>", table_cell_bold),
            Paragraph("<b>Key Compiler Concept Demonstrated</b>", table_cell_bold),
            Paragraph("<b>Target Faculty Question Answered</b>", table_cell_bold),
        ],
        [
            Paragraph("1", table_cell),
            Paragraph("python -m unittest discover -s tests -v", table_cell_cmd),
            Paragraph("76/76 passing tests across all phases", table_cell),
            Paragraph("\"Is the implementation thoroughly tested?\"", table_cell),
        ],
        [
            Paragraph("2", table_cell),
            Paragraph(".\\toycompiler.bat dfa-stats", table_cell_cmd),
            Paragraph("Moore's minimization (67 states, 62 accepting)", table_cell),
            Paragraph("\"How did you implement lexical analysis?\"", table_cell),
        ],
        [
            Paragraph("3", table_cell),
            Paragraph(".\\toycompiler.bat run examples\\valid_factorial.toy --ast --symbols", table_cell_cmd),
            Paragraph("Precedence AST + Scoped Symbol Table", table_cell),
            Paragraph("\"How is grammar precedence and scope handled?\"", table_cell),
        ],
        [
            Paragraph("4", table_cell),
            Paragraph(".\\toycompiler.bat run examples\\err_multiple.toy", table_cell_cmd),
            Paragraph("Panic-mode statement synchronization", table_cell),
            Paragraph("\"Does the parser recover from syntax errors?\"", table_cell),
        ],
        [
            Paragraph("5", table_cell),
            Paragraph(".\\toycompiler.bat diagnose examples\\err_missing_semicolon.toy --online", table_cell_cmd),
            Paragraph("Groq LLM delimiter repair + [VERIFIED FIX] diff", table_cell),
            Paragraph("\"How does LLM repair work with verification?\"", table_cell),
        ],
        [
            Paragraph("6", table_cell),
            Paragraph(".\\toycompiler.bat diagnose examples\\benchmarks\\12_sem_var_typo.toy --online", table_cell_cmd),
            Paragraph("Symbol table slice injection + typo repair", table_cell),
            Paragraph("\"What context does the LLM receive?\"", table_cell),
        ],
        [
            Paragraph("7", table_cell),
            Paragraph(".\\toycompiler.bat run examples\\benchmarks\\12_sem_var_typo.toy --json", table_cell_cmd),
            Paragraph("Typed Diagnostic JSON schema", table_cell),
            Paragraph("\"How is internal compiler state exported?\"", table_cell),
        ],
        [
            Paragraph("8", table_cell),
            Paragraph(".\\toycompiler.bat eval --output evaluation_report.md --json", table_cell_cmd),
            Paragraph("20-program comparative study & ablation", table_cell),
            Paragraph("\"What is the quantitative evaluation result?\"", table_cell),
        ],
    ]

    summary_table = Table(table_data, colWidths=[24, 185, 165, 166])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#E2E8F0")),
        ('GRID', (0, 0), (-1, -1), 0.5, c_border),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
    ]))
    story.append(summary_table)

    doc.build(story, canvasmaker=NumberedCanvas)
    print(f"Successfully generated: {output_filename}")


if __name__ == "__main__":
    create_pdf()
