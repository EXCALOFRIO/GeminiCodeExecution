# Code Executor with Gemini Integration 🚀


## Description 📝

This project provides a **secure and isolated** environment to run Python code generated by Google's Gemini API. Think of it as a sandbox for AI-generated code! ✨ It uses Docker for safety, manages dependencies automatically, and handles files. Perfect for experimenting without risking your system. 🛡️

## Key Features 🌟

*   **Gemini-Powered:** Code generation & dependency management via Gemini API.
*   **Docker Isolation:** Runs code in a secure container.
*   **Auto-Dependencies:** Installs needed packages from `requirements.txt`.
*   **File Handling:** Input & output file support.
*   **Code Formatting:** Clean, readable code.
*   **Caching**: Docker images are cached based on dependencies.

## Prerequisites ✅

*   **Python 3.7+**
*   **Docker:** [Install Docker](https://www.docker.com/get-started)
*   **Gemini API Key (`GEMINI_API_KEY`):**  Set as an environment variable.

## Installation ⚙️

1.  **Clone:** `git clone <repository_url>`
2.  **Enter:** `cd <repository_directory>`
3.  **Virtual Environment:** `python -m venv venv`
    *   **Activate:**
        *   Windows: `venv\Scripts\activate`
        *   Linux/macOS: `source venv/bin/activate`
4.  **Install Dependencies:** `pip install -r requirements.txt`
5.  **Set API Key:**
    *   Windows: `setx GEMINI_API_KEY "<your_api_key>" /M` (restart terminal)
    *   Linux/macOS: `export GEMINI_API_KEY="<your_api_key>"` (add to `.bashrc`, etc.)

## Usage 🚀

### 1. Build the Base Docker Image:
    ```bash
    docker build -t python_executor:latest ./executor
    ```
### 2. Run the Streamlit App
    ```bash
    streamlit run app.py
    ```

**That's it!** 🎉  The Streamlit app will guide you through the code generation and execution process.

## Core Components 🧩

*   `file_formatter.py`: Formats file outputs (CSV, images, etc.).
*   `gemini_client.py`:  Talks to the Gemini API.
*   `code_formatter.py`: Cleans up the generated code.
*   `docker_executor.py`: Runs code in Docker.
*   `executor/Dockerfile`: Defines the base Docker image.
*   `requirements.txt`: Project dependencies.

## Troubleshooting 🐛

*   **Docker:**  Is Docker running? Check logs.
*   **API Key:**  Valid `GEMINI_API_KEY`?
*   **Dependencies:**  `requirements.txt` correct?
*   **Errors:** Check `stderr` output.

## Contributing 🤝

Pull requests welcome!  Let's make this awesome. 💪

## License 📜

[MIT License]