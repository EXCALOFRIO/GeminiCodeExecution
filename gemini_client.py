import os
import random
import google.generativeai as genai

# Global variables to store API keys and current index
_API_KEYS = []
_API_KEY_INDEX = 0

def load_api_keys():
    """
    Loads all Gemini API keys from environment variables with prefix 'GEMINI_API_KEY'
    and sets a random initial index.
    """
    global _API_KEYS, _API_KEY_INDEX
    keys = [value for key, value in os.environ.items() if key.startswith("GEMINI_API_KEY") and value]
    if not keys:
        raise ValueError("No Gemini API keys found in environment variables with prefix GEMINI_API_KEY.")
    _API_KEYS = keys
    _API_KEY_INDEX = random.randrange(len(_API_KEYS))

def configure_gemini():
    """
    Configures the Gemini API using a round-robin selected key.
    """
    global _API_KEYS, _API_KEY_INDEX
    if not _API_KEYS:
        load_api_keys()
    api_key = _API_KEYS[_API_KEY_INDEX]
    _API_KEY_INDEX = (_API_KEY_INDEX + 1) % len(_API_KEYS)
    genai.configure(api_key=api_key)

def clean_generated_code(text: str) -> str:
    """
    Cleans generated text by removing Markdown delimiters and unnecessary spaces.
    """
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # Remove first line if it contains code delimiter
        lines = lines[1:] if lines and lines[0].startswith("```") else lines
        # Remove last line if it contains code delimiter
        lines = lines[:-1] if lines and lines[-1].strip().startswith("```") else lines
        text = "\n".join(lines)
    # Remove language identifier if exists (e.g., ```python)
    if text.startswith("python") or text.startswith("Python"):
        lines = text.splitlines()
        text = "\n".join(lines[1:])
    return text.strip()

def generate_code(prompt: str, model_name: str = "gemini-2.0-flash-001") -> str:
    """
    Generates content using the Gemini API based on the provided prompt.
    If an error occurs, retries with another API key until all available keys are exhausted.
    """
    if not _API_KEYS:
        load_api_keys()
    
    num_keys = len(_API_KEYS)
    errors = []
    
    for _ in range(num_keys):
        configure_gemini()
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)
            code = response.text.strip()
            return clean_generated_code(code)
        except Exception as e:
            errors.append(str(e))
            continue
    raise RuntimeError(f"Error generating content with Gemini (model: {model_name}) after {num_keys} attempts. Errors: {errors}")

def generate_thought_chain(initial_prompt: str, iterations: int, model_name: str = "gemini-2.0-flash-001") -> str:
    """
    Generates a step-by-step chain of thought based on the initial prompt and number of iterations.
    """
    if iterations <= 0:
        return ""
    thought = initial_prompt
    for i in range(iterations):
        prompt = (
            f"# INSTRUCTION\n"
            f"Analyze the following information deeply, exploring all technical aspects of the problem or results:\n\n"
            f"```\n{thought}\n```\n\n"
            f"# RESPONSE FORMAT\n"
            f"Provide a detailed technical reasoning in Spanish following these specific steps:\n"
            f"1. **Problem context**: Identify key elements, constraints, and variables in the provided information.\n"
            f"2. **Objectives**: Clearly state what we're trying to achieve and what specific questions need answering.\n"
            f"3. **Technical analysis**: Perform a comprehensive technical analysis of the data, code, or instructions.\n"
            f"4. **Solution approaches**: Propose concrete strategies and algorithms to solve the problem, evaluating trade-offs.\n"
            f"5. **Potential obstacles**: Identify limitations, edge cases, or potential issues that might arise.\n"
            f"6. **Implementation plan**: Detail the specific steps to follow to implement the optimal solution.\n"
            f"7. **Success criteria**: Define specific metrics and methods to evaluate if the solution is effective.\n"
            f"8. **Critical insights**: Highlight the most important discoveries or insights from your analysis.\n\n"
            f"# CONSTRAINTS\n"
            f"- DO NOT include phrases like 'Based on the provided information' or similar.\n"
            f"- DO NOT reproduce the original problem statement or code delimiters.\n"
            f"- MAINTAIN a highly technical, detailed focus throughout.\n"
            f"- PRIORITIZE clarity, precision, and thoroughness in your analysis.\n"
            f"- WRITE your entire response in fluent, technical Spanish.\n"
            f"- AVOID generic statements—every sentence should contain specific, substantive insights."
        )
        thought = generate_code(prompt, model_name=model_name)
    return thought

def review_code(code: str, model_name: str = "gemini-2.0-flash-001") -> str:
    """
    Generates a code analysis to identify potential errors or areas for improvement.
    """
    prompt = (
        "# INSTRUCTION\n"
        "Perform a comprehensive expert-level analysis of the following Python code:\n\n"
        f"```python\n{code}\n```\n\n"
        "# RESPONSE FORMAT\n"
        "Structure your analysis in Spanish with these clearly differentiated sections:\n"
        "1. **Executive summary**: General code description and purpose (2-3 sentences).\n"
        "2. **Critical errors**: Identify all bugs, syntax errors, or logical errors that prevent execution.\n"
        "3. **Performance issues**: Identify bottlenecks, inefficient operations, or problematic patterns.\n"
        "4. **Security vulnerabilities**: Detect potential risks such as injections, insecure data handling, etc.\n"
        "5. **Code quality & maintainability**: Evaluate organization, readability, modularity, and PEP 8 adherence.\n"
        "6. **Dependencies & compatibility**: Analyze libraries used and potential compatibility issues.\n"
        "7. **Prioritized recommendations**: List specific improvements ordered by importance with code examples.\n"
        "8. **Testing strategy**: Suggest specific test cases to validate the functionality.\n\n"
        "# CONSTRAINTS\n"
        "- DO NOT include the original code in your response.\n"
        "- DO NOT use generic markers like 'Error 1', 'Problem 2'.\n"
        "- BE specific when pointing out problems, indicating exact line numbers and context.\n"
        "- MAINTAIN a technical and objective tone, without unnecessary justifications.\n"
        "- WRITE your entire response in fluent, technical Spanish.\n"
        "- PROVIDE code snippets for each recommendation showing proper implementation."
    )
    return generate_code(prompt, model_name=model_name)

def improve_code_based_on_review(code: str, review: str, model_name: str = "gemini-2.0-flash-001") -> str:
    """
    Improves the code based on the provided analysis.
    """
    prompt = (
        "# INSTRUCTION\n"
        "Improve the following Python code by implementing all recommendations from the technical analysis:\n\n"
        f"## ORIGINAL CODE\n```python\n{code}\n```\n\n"
        f"## TECHNICAL ANALYSIS\n```\n{review}\n```\n\n"
        "# RESPONSE FORMAT\n"
        "Provide only the complete and improved Python code, implementing all corrections and enhancements identified in the analysis.\n\n"
        "# REQUIREMENTS\n"
        "1. The code must be complete and fully functional in a single Python file.\n"
        "2. It must generate visualizations as images (PNG, JPG) or animated graphs (GIF, MP4).\n"
        "3. It must export data for analysis (CSV, Excel, JSON) when appropriate.\n"
        "4. All generated files must be saved in the project root.\n"
        "5. Include robust error handling and clear documentation.\n"
        "6. The code must be optimized for performance and security.\n"
        "7. Add comprehensive docstrings and helpful inline comments in Spanish.\n\n"
        "# CONSTRAINTS\n"
        "- DO NOT include explanations, notes, or introductory comments.\n"
        "- DO NOT use markdown delimiters (```) at the beginning or end.\n"
        "- DO NOT omit sections of code with comments like '# rest of code...'.\n"
        "- INCLUDE relevant explanatory comments within the code in Spanish.\n"
        "- ENSURE the output code is production-ready and follows best practices."
    )
    return generate_code(prompt, model_name=model_name)

def review_report(report: str, model_name: str = "gemini-2.0-flash-001") -> str:
    """
    Generates an analysis of the report to identify how to improve the analysis and conclusions.
    """
    prompt = (
        "# INSTRUCTION\n"
        "Evaluate the following technical report in Markdown format as a senior data scientist or technical expert:\n\n"
        f"```markdown\n{report}\n```\n\n"
        "# RESPONSE FORMAT\n"
        "Structure your evaluation in Spanish with these sections:\n"
        "1. **General evaluation**: Overall assessment of the report's quality, coherence, and effectiveness.\n"
        "2. **Strengths**: Positive aspects and well-executed elements of the report.\n"
        "3. **Critical weaknesses**: Fundamental problems that compromise validity or usefulness.\n"
        "4. **Section-by-section analysis**: Detailed evaluation of each main section.\n"
        "5. **Methodological rigor**: Evaluation of methodology, statistical analysis, and validity of conclusions.\n"
        "6. **Data visualization**: Critique of graphs, tables, and visual elements.\n"
        "7. **Specific recommendations**: Concrete and prioritized suggestions to improve the report, with examples.\n"
        "8. **Scientific accuracy**: Assessment of how well the report adheres to scientific standards.\n\n"
        "# CONSTRAINTS\n"
        "- DO NOT reproduce the original content of the report.\n"
        "- DO NOT use ambiguous or generic language in your critiques.\n"
        "- BE specific when pointing out problems, citing exact text when relevant.\n"
        "- MAINTAIN a technical, constructive, and objective tone.\n"
        "- FOCUS on content and structure, not on markdown formatting issues.\n"
        "- WRITE your entire response in fluent, technical Spanish.\n"
        "- INCLUDE examples of how specific sections could be improved."
    )
    return generate_code(prompt, model_name=model_name)

def improve_report_based_on_review(report: str, review: str, model_name: str = "gemini-2.0-flash-001") -> str:
    """
    Improves the report based on the provided analysis.
    """
    prompt = (
        "# INSTRUCTION\n"
        "Improve the following scientific report in Markdown by implementing all recommendations from the technical review:\n\n"
        f"## ORIGINAL REPORT\n```markdown\n{report}\n```\n\n"
        f"## TECHNICAL REVIEW\n```\n{review}\n```\n\n"
        "# RESPONSE FORMAT\n"
        "Provide the complete improved report in Markdown incorporating all recommended enhancements.\n\n"
        "# REQUIREMENTS\n"
        "1. Maintain the same general structure but improve each section according to the analysis.\n"
        "2. Strengthen scientific rigor, clarity, and data presentation.\n"
        "3. Preserve references to visualizations with the format `{{visualize_filename}}`.\n"
        "4. Ensure the analysis is thorough, conclusions are solid, and language is precise.\n"
        "5. Add any missing sections that would enhance the scientific quality.\n"
        "6. Reorganize content if needed to improve logical flow and readability.\n"
        "7. Ensure all technical terms are accurate and appropriately explained.\n\n"
        "# CONSTRAINTS\n"
        "- DO NOT include explanations about changes made.\n"
        "- DO NOT use markdown delimiters (```) at the beginning or end.\n"
        "- DO NOT omit any important section from the original report.\n"
        "- MAINTAIN pure Markdown format (no HTML).\n"
        "- WRITE the entire report in fluent, technical Spanish.\n"
        "- ENSURE consistent terminology and notation throughout the document."
    )
    return generate_code(prompt, model_name=model_name)

def get_dependencies(code: str, model_name: str = "gemini-2.0-flash-001") -> str:
    """
    Generates a list of required dependencies in 'requirements.txt' format.
    """
    prompt = (
        "# INSTRUCTION\n"
        "Analyze the following Python code and generate a comprehensive and precise requirements.txt file:\n\n"
        f"```python\n{code}\n```\n\n"
        "# RESPONSE FORMAT\n"
        "Provide only the content of the requirements.txt file, with each dependency on a separate line.\n\n"
        "# REQUIREMENTS\n"
        "1. Include ALL libraries imported in the code, both explicitly and implicitly.\n"
        "2. Specify exact versions for each package using the `package==version` format.\n"
        "3. Include critical secondary dependencies that may be necessary.\n"
        "4. Sort dependencies alphabetically.\n"
        "5. For visualizations, ensure all necessary dependencies are included (matplotlib, plotly, etc.).\n"
        "6. Don't forget data processing libraries (pandas, numpy) if used.\n"
        "7. Use the latest stable version of each package as of February 2025.\n"
        "8. For packages with complex dependencies, ensure version compatibility.\n\n"
        "# CONSTRAINTS\n"
        "- DO NOT include explanations or comments.\n"
        "- DO NOT use markdown delimiters (```).\n"
        "- DO NOT include system packages (only pip packages).\n"
        "- IF no dependencies are needed, return an empty string.\n"
        "- ENSURE all specified versions are actually available on PyPI."
    )
    result = generate_code(prompt, model_name=model_name)
    return result.strip()

def refine_code(previous_code: str, outputs: dict, thought_chain: str, error_history: list = None, model_name: str = "gemini-2.0-flash-001") -> str:
    """
    Corrects and improves Python code based on execution results, thought chain, and complete error history.
    
    Args:
        previous_code (str): Previous code.
        outputs (dict): Execution results (stdout, stderr, etc.).
        thought_chain (str): Previously generated thought chain.
        error_history (list, optional): List with complete error history.
        model_name (str): Model name to use.
    
    Returns only complete and functional code, without comments or delimiters.
    """
    if error_history is None:
        error_history = []
    error_history_str = "\n".join(error_history)
    outputs_str = "\n".join(f"{k}: {v}" for k, v in outputs.items())
    prompt = (
        "# CONTEXT\n"
        f"## PREVIOUS ANALYSIS\n```\n{thought_chain}\n```\n\n"
        f"## ERROR HISTORY\n```\n{error_history_str}\n```\n\n"
        f"## CURRENT CODE\n```python\n{previous_code}\n```\n\n"
        f"## EXECUTION RESULTS\n```\n{outputs_str}\n```\n\n"
        "# INSTRUCTION\n"
        "Fix the Python code to resolve all identified errors and issues. Apply a fundamentally different approach if necessary.\n\n"
        "# RESPONSE FORMAT\n"
        "Provide only the complete and corrected Python code.\n\n"
        "# REQUIREMENTS\n"
        "1. The code must be complete in a single Python file.\n"
        "2. It must solve ALL errors identified in the execution results.\n"
        "3. It must generate visualizations as images (PNG, JPG) or animated graphs (GIF, MP4).\n"
        "4. It must export data for analysis (CSV, Excel, JSON) when appropriate.\n"
        "5. All generated files must be saved in the project root.\n"
        "6. The code must be substantially different from the previous version, addressing the root cause of errors.\n"
        "7. Include robust error handling with specific exception types.\n"
        "8. Add comprehensive logging to facilitate debugging.\n\n"
        "# CONSTRAINTS\n"
        "- DO NOT include explanations, notes, or introductory comments.\n"
        "- DO NOT use markdown delimiters (```) at the beginning or end.\n"
        "- DO NOT omit sections of code with comments like '# rest of code...'.\n"
        "- INCLUDE relevant explanatory comments within the code in Spanish.\n"
        "- WRITE all docstrings and comments in Spanish.\n"
        "- ENSURE the solution is significantly different if previous approaches failed."
    )
    return generate_code(prompt, model_name=model_name)

def refine_dependencies(previous_deps: str, code: str, outputs: dict, thought_chain: str, error_history: list = None, model_name: str = "gemini-2.0-flash-001") -> str:
    """
    Corrects the dependency list based on thought chain, execution results, and complete error history.
    
    Args:
        previous_deps (str): Previous dependency list.
        code (str): Code being evaluated.
        outputs (dict): Execution results.
        thought_chain (str): Generated thought chain.
        error_history (list, optional): Complete error history.
        model_name (str): Model name to use.
    
    Returns only the updated list in 'requirements.txt' format, without explanations or delimiters.
    """
    if error_history is None:
        error_history = []
    error_history_str = "\n".join(error_history)
    outputs_str = "\n".join(f"{k}: {v}" for k, v in outputs.items())
    prompt = (
        "# CONTEXT\n"
        f"## PREVIOUS ANALYSIS\n```\n{thought_chain}\n```\n\n"
        f"## ERROR HISTORY\n```\n{error_history_str}\n```\n\n"
        f"## CURRENT CODE\n```python\n{code}\n```\n\n"
        f"## CURRENT DEPENDENCIES\n```\n{previous_deps}\n```\n\n"
        f"## EXECUTION RESULTS\n```\n{outputs_str}\n```\n\n"
        "# INSTRUCTION\n"
        "Fix the requirements.txt file to resolve all dependency errors identified. Focus specifically on Python package issues in the execution results.\n\n"
        "# RESPONSE FORMAT\n"
        "Provide only the corrected content of the requirements.txt file, with each dependency on a separate line.\n\n"
        "# REQUIREMENTS\n"
        "1. Include ALL libraries needed to run the code without errors.\n"
        "2. Specify exact versions for each package using the `package==version` format.\n"
        "3. Pay special attention to import errors or ModuleNotFoundError in the results.\n"
        "4. Ensure all data handling, visualization, and processing dependencies are included.\n"
        "5. Fix version conflicts if present in the error logs.\n"
        "6. Add any missing dependencies that could be causing the errors.\n"
        "7. Remove dependencies that might be causing conflicts.\n"
        "8. Ensure compatibility with Python 3.9+ environments.\n\n"
        "# CONSTRAINTS\n"
        "- DO NOT include explanations or comments.\n"
        "- DO NOT use markdown delimiters (```).\n"
        "- DO NOT include system packages (only pip packages).\n"
        "- ENSURE versions are mutually compatible.\n"
        "- FOCUS on dependencies that directly address the errors in execution results."
    )
    return generate_code(prompt, model_name=model_name).strip()

def improve_code(previous_code: str, additional_instructions: str, thought_chain: str, model_name: str = "gemini-2.0-flash-001") -> str:
    """
    Generates an improved version of Python code based on additional instructions and thought chain.
    """
    prompt = (
        "# CONTEXT\n"
        f"## PREVIOUS ANALYSIS\n```\n{thought_chain}\n```\n\n"
        f"## CURRENT CODE\n```python\n{previous_code}\n```\n\n"
        f"## ADDITIONAL INSTRUCTIONS\n```\n{additional_instructions}\n```\n\n"
        "# INSTRUCTION\n"
        "Improve the Python code following the additional instructions and previous analysis. Make substantial enhancements beyond the requested changes.\n\n"
        "# RESPONSE FORMAT\n"
        "Provide only the complete and improved Python code.\n\n"
        "# REQUIREMENTS\n"
        "1. The code must be complete in a single Python file.\n"
        "2. It must implement ALL improvements requested in the additional instructions.\n"
        "3. It must generate visualizations as images (PNG, JPG) or animated graphs (GIF, MP4).\n"
        "4. It must export data for analysis (CSV, Excel, JSON) when appropriate.\n"
        "5. All generated files must be saved in the project root.\n"
        "6. The code must be executable in a Docker environment without additional configuration.\n"
        "7. Add comprehensive error handling and logging mechanisms.\n"
        "8. Improve code organization, modularity, and documentation.\n\n"
        "# CONSTRAINTS\n"
        "- DO NOT include explanations, notes, or introductory comments.\n"
        "- DO NOT use markdown delimiters (```) at the beginning or end.\n"
        "- DO NOT omit sections of code with comments like '# rest of code...'.\n"
        "- INCLUDE relevant explanatory comments within the code in Spanish.\n"
        "- WRITE all docstrings and comments in Spanish.\n"
        "- ENSURE significant improvements beyond just implementing the requested changes."
    )
    return generate_code(prompt, model_name=model_name)

def generate_markdown_report(stdout: str, stderr: str, image_files: list, data_files: list, thought_chain: str, model_name: str = "gemini-2.0-flash-001") -> str:
    """
    Generates a Markdown report based on execution results and thought chain.
    """
    images = ", ".join(image_files) if image_files else "None"
    data = ", ".join(data_files) if data_files else "None"
    prompt = (
        "# CONTEXT\n"
        f"## PREVIOUS ANALYSIS\n```\n{thought_chain}\n```\n\n"
        f"## GENERATED FILES\n"
        f"- Images: {images}\n"
        f"- Data: {data}\n\n"
        f"## STANDARD OUTPUT\n```\n{stdout}\n```\n\n"
        f"## ERRORS\n```\n{stderr}\n```\n\n"
        "# INSTRUCTION\n"
        "Generate a comprehensive scientific report in Markdown format that analyzes the obtained results with depth and technical precision.\n\n"
        "# RESPONSE FORMAT\n"
        "Provide only the scientific report in Markdown, structured and professional.\n\n"
        "# REQUIREMENTS\n"
        "1. Report structure:\n"
        "   - Descriptive title\n"
        "   - Executive summary (abstract)\n"
        "   - Introduction and context\n"
        "   - Methodology with technical details\n"
        "   - Results with detailed analysis\n"
        "   - Discussion of implications and limitations\n"
        "   - Conclusions with key insights\n"
        "   - Future work recommendations\n"
        "   - References (if applicable)\n\n"
        "2. For each image, include:\n"
        "   - Detailed technical description\n"
        "   - Analysis of observed patterns\n"
        "   - Scientific interpretation with supporting theory\n"
        "   - Limitations and considerations\n"
        "   - Comparative analysis with expected results\n\n"
        "3. For each data file, include:\n"
        "   - Description of structure and content\n"
        "   - Relevant statistical analysis\n"
        "   - Interpretation of trends or findings\n"
        "   - Data quality assessment\n"
        "   - Recommendations based on data insights\n\n"
        "4. To reference files, use the marker `{{visualize_filename}}` where appropriate.\n\n"
        "# CONSTRAINTS\n"
        "- DO NOT analyze or mention the source code.\n"
        "- DO NOT use HTML within the Markdown.\n"
        "- DO NOT use markdown delimiters (```) at the beginning or end of the report.\n"
        "- DO NOT include quotes around {{visualize_filename}} markers.\n"
        "- MAINTAIN a scientific, objective, and technical tone throughout the report.\n"
        "- WRITE the entire report in fluent, technical Spanish.\n"
        "- ENSURE each section contains substantive, specific insights rather than generic statements."
    )
    return generate_code(prompt, model_name=model_name)

def classify_execution_error(combined_output: str, model_name: str = "gemini-2.0-flash-001") -> str:
    """
    Classifies the error type based on combined execution output using Gemini.
    """
    prompt = (
        "# INSTRUCTION\n"
        "Analyze the following execution output from a Python script in Docker and classify the primary error type.\n\n"
        f"```\n{combined_output}\n```\n\n"
        "# RESPONSE FORMAT\n"
        "Respond with ONLY ONE WORD from the following options:\n"
        "- 'DEPENDENCY': If the main error is related to missing or incompatible dependencies.\n"
        "- 'CODE': If the error is in the logic or syntax of the code.\n"
        "- 'BOTH': If there are both dependency and code errors.\n"
        "- 'OK': If there are no errors and execution was successful.\n\n"
        "# CONSTRAINTS\n"
        "- RESPOND ONLY with one of the four options in uppercase.\n"
        "- DO NOT include explanations or justifications.\n"
        "- DO NOT use delimiters, quotes, or additional punctuation.\n"
        "- ANALYZE carefully 'ImportError', 'ModuleNotFoundError' (DEPENDENCY) vs 'SyntaxError', 'TypeError', etc. (CODE).\n"
        "- PRIORITIZE the most critical error type if multiple are present."
    )
    response = generate_code(prompt, model_name=model_name)
    classification = response.strip().upper()
    if classification in ["DEPENDENCY", "CODE", "BOTH", "OK"]:
        return classification
    else:
        return "UNKNOWN"