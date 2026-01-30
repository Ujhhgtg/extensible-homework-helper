# 📚 Extensible Homework Helper

A powerful command-line tool designed to automate login, homework list parsing, and content extraction (including audio downloading and transcription) from the [简练英语平台](https://admin.jeedu.net) platform using httpx & BeautifulSoup and OpenAI's Whisper.

## ✨ Features

- Structured Homework Overview: Scrapes and presents a clear, structured list of all pending and completed homework, including scores and completion status.

- Content Retrieval: Easily retrieve the complete text content of any homework assignment.

- Audio Management: Download embedded audio files for self-study or automated transcription.

- Accurate Transcription: Utilizes the powerful Whisper model for highly accurate English transcription of downloaded homework audio.

- AI-Powered Answers: Generates potential answers using any OpenAI-compatible LLM to assist with your assignments.

- Interactive Interface: Provides a dynamic, user-friendly command-line interface powered by `prompt_toolkit`.

- 2 Operation Modes: Browser automation-based (using Selenium) and API-based (using httpx & BeautifulSoup)

## 🚀 Setup & Installation

### Prerequisites

You need to have Python 3.12+ installed on your system.

### 1. Install package

#### A. From source, with uv

```bash
uv tool install git+https://github.com/Ujhhgtg/extensible-homework-helper.git
```

#### B. From source, manually

```bash
git clone https://github.com/Ujhhgtg/extensible-homework-helper.git
cd extensible-homework-helper
uv sync # 请用 uv 谢谢喵
uv build
uv pip install ./dist/*.tar.gz

# optional: install pytorch for audio transcription
uv pip install openai-whisper
just install-torch-[torch backend]

# optional: you can also install optional dependencies for more features
# refer to pyproject.toml for now
uv sync --extra tg-bot
```

### 3. Configure settings

> [!NOTE]
> Some configuration options are optional, however you won't be able to access advanced features if you skip them.

Rename `config.yaml.example` to `config.yaml` and fill it in. The script will automatically move it to an appropriate location.

## 🔑 Guide: How to use LLMs for free

To use the AI-powered features, you'll need an API key from an LLM provider. This tool is compatible with OpenAI (e.g., ChatGPT models) and other OpenAI-compatible models including Google's Gemini (via its API endpoint) and Ollama.

### Google Gemini (Cloud)

> [!NOTE]
> The Gemini API has a free tier, but usage is subject to limits and billing.

1. Go to [Google AI Studio](https://aistudio.google.com/app/api-keys).

2. Sign in with your Google account.

3. Click `Create API key`. You may need to select or create a Google Cloud Project.

4. Copy the generated key and keep it secure.

5. Add in `config.yaml`.

### Ollama (Local)

> [!NOTE]
> Although Ollama can be run locally, the quality is often worse since most setups can only run highly-distilled models.

1. Install Ollama: Follow the instructions for your operating system on the [Ollama website](https://ollama.com/download).

2. Run the server:

    ```bash
    ollama serve
    ```

3. Pull a model. You can find models on the [Ollama Library](https://ollama.com/library).

    ```bash
    ollama pull model-name
    ```

## 💻 Usage

Run the main script:

```bash
# api version
uv run python -m ehh.repl
```

## 🤝 Contributing

This project is a personal utility. If you find it useful or have suggestions for improvement, feel free to open an issue or submit a pull request!
