# Code Executor with Gemini Integration

## Description

This project provides a secure and isolated environment for executing Python code generated by the Google Gemini API.  It leverages Docker for sandboxing, ensuring that potentially unsafe code doesn't compromise the host system.  Key features include:

*   **Gemini Integration:**  Generates Python code snippets and dependency lists using the Gemini API.  Requires a valid `GEMINI_API_KEY` environment variable.
*   **Dependency Management:**  Automatically identifies and installs required Python packages using `requirements.txt`. Caches Docker images based on dependencies for faster execution.
*   **Docker Isolation:** Executes code within a Docker container, providing a clean and controlled environment.
*   **File Handling:** Supports providing input files to the code and retrieving generated files after execution.
*   **Code Formatting:** Cleans and formats generated code for readability.
*   **Error Handling:** Captures and displays standard output and standard error streams from the container execution.
*   **Caching**: Docker images are cached based on the dependencies to speed up future executions.
*   **Streamlit Interface (Optional)**: The original project includes a Streamlit interface, but this `README` focuses on the core functionality.
*   **Modular Design**: The project is structured in a modular way with dedicated files for file formatting, Gemini API interaction, code cleaning and docker execution.

## Core Components:

*   `file_formatter.py`: Formats the display of generated files based on their extensions (e.g., CSV to HTML table, images as previews).
*   `gemini_client.py`: Handles communication with the Google Gemini API for code generation, dependency extraction, and code refinement.
*   `code_formatter.py`: Cleans and formats generated code by removing Markdown delimiters and unnecessary characters.
*   `docker_executor.py`: Executes Python code within a Docker container, manages dependencies, and handles input/output files.
*   `executor/Dockerfile`: Dockerfile used to build the base Docker image.
*   `requirements.txt`: Lists the Python dependencies required to run the project.

## Prerequisites

Before you begin, ensure you have the following installed:

*   **Python 3.7+**
*   **Docker:**  [Install Docker Desktop](https://www.docker.com/products/docker-desktop/) (for Windows and macOS) or [Docker Engine](https://docs.docker.com/engine/install/) (for Linux).
*   **`GEMINI_API_KEY`:** You need an API key from Google Gemini.  Set this as an environment variable.

## Installation

1.  **Clone the Repository:**

    ```bash
    git clone <repository_url>
    cd <repository_directory>
    ```

2.  **Create a Virtual Environment (Recommended):**

    ```bash
    python -m venv venv
    ```

    *   **On Windows:**

        ```bash
        venv\Scripts\activate
        ```

    *   **On Linux/macOS:**

        ```bash
        source venv/bin/activate
        ```

3.  **Install Dependencies:**

    ```bash
    pip install -r requirements.txt
    ```

4.  **Set the `GEMINI_API_KEY` Environment Variable:**

    *   **On Windows:**

        ```bash
        setx GEMINI_API_KEY "<your_api_key>" /M  # Sets it system-wide
        ```

        (You may need to restart your terminal or command prompt for the change to take effect.)  Alternatively, set it just for the current session:

         ```bash
         set GEMINI_API_KEY=<your_api_key>
         ```

    *   **On Linux/macOS:**

        ```bash
        export GEMINI_API_KEY="<your_api_key>"
        ```

        (Add this line to your `.bashrc`, `.zshrc`, or equivalent shell configuration file for persistence.)

## Usage

Here's a basic example of how to use the core functions.  This assumes you're comfortable working in a Python environment.

```python
from gemini_client import generate_code, execute_code_in_docker, get_dependencies, refine_code
from docker_executor import initialize_docker_image
import os

# Build the base docker image
print(initialize_docker_image())

# Example usage
prompt = "Escribe una función en python que calcule el factorial de un número."
code = generate_code(prompt)

print("Generated Code:\n", code)

# Get dependencies
dependencies = get_dependencies(code)
print("Dependencies:\n", dependencies)

# Example input files
input_files = {}

# Execute the code
execution_result = execute_code_in_docker(code, input_files, dependencies)

print("Execution Result:\n", execution_result)

# Example of refining the code after execution
# refined_code = refine_code(code, execution_result)
# print("Refined Code:\n", refined_code)

# Example of generating a simple image
code_image = """
from PIL import Image
import numpy as np

# Define the image size
width, height = 256, 256

# Create a red image
red_channel = np.full((height, width), 255, dtype=np.uint8)  # Red channel is fully on
green_channel = np.zeros((height, width), dtype=np.uint8)   # Green channel is off
blue_channel = np.zeros((height, width), dtype=np.uint8)    # Blue channel is off

# Stack the channels to create an RGB image
image_array = np.stack([red_channel, green_channel, blue_channel], axis=2)

# Create a PIL Image object from the numpy array
image = Image.fromarray(image_array)

# Save the image as a PNG file
image.save("red_image.png")
"""

dependencies_image = get_dependencies(code_image)
input_files_image = {}
execution_result_image = execute_code_in_docker(code_image, input_files_image, dependencies_image)

if execution_result_image and execution_result_image["files"]:
    with open("red_image.png", "wb") as f:
        f.write(execution_result_image["files"]["red_image.png"])
    print("Image 'red_image.png' saved successfully.")
else:
    print("Failed to generate or save the image.")
