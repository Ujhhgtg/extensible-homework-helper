COMPLETION_WORD_MAP = {
    (): [
        "list",
        "audio",
        "text",
        "answers",
        "help",
        "account",
        "ai",
        "config",
        "exit",
    ],
    ("audio",): ["download", "transcribe"],
    ("text",): ["display", "download"],
    ("answers",): ["download", "fill_in", "generate", "download_from_paper", "submit"],
    ("account",): ["login", "logout", "select_default"],
    ("ai",): ["select_api", "select_model"],
    ("config",): ["reload", "save"],
}


GENERATE_ANSWERS_WITH_LISTENING_PROMPT = """
Complete the following questions.

Listening audio transcription:
```
{transcription}
```

Questions:
```
{questions}
```

Output format (index starts at 1): 
```
[
    {
        "index": 1,
        "kind": "choice",
        "content": "A"
    },
    # other answers
]
```

Output requirements:
1. NO MARKDOWN, NO COMMENTS, ONLY PURE JSON
2. For the groups of questions that lets you fill words/sentences into the blanks inside a whole passage: (1) treat them as "fill-in-blanks" questions, but fill in the letters that represents the words instead of the words themselves. (2) you must not use words/sentences repeatedly. one word/sentence can be used only 0~1 times.
3. There are only two kinds: "choice" and "fill-in-blanks". Treat translations as "fill-in-blanks" questions.
"""

GENERATE_ANSWERS_PROMPT = """
Complete the following questions.

Questions:
```
{questions}
```

Output format (index starts at 1):
```
[
    {
        "index": 1,
        "kind": "choice",
        "content": "A"
    },
    {
        "index": 2,
        "kind": "fill-in-blanks",
        "content": "answer to the question"
    },
    # other answers
]
```

Output requirements:
1. NO MARKDOWN, NO COMMENTS, ONLY PURE JSON
2. For the vocabulary part that lets you fill words into the blanks inside a whole passage, treat them as "fill-in-blanks" questions, but fill in the letters that represents the words instead of the words themselves.
3. There are only two kinds: "choice" and "fill-in-blanks". Treat translations as "fill-in-blanks" questions.
"""

GENERATE_TRANSLATION_ANSWERS_PROMPT = """
Translate the following sentences from Chinese to English.

SENTENCES:
```
{questions}
```

Output format (index starts at 1):
```
[
    {
        "index": 1,
        "kind": "translation",
        "content": "Hello world!"
    },
    {
        "index": 2,
        "kind": "translation",
        "content": "Another sentence translated."
    },
    # other answers
]
```

Output requirements:
1. NO MARKDOWN, NO COMMENTS, ONLY PURE JSON
2. There is only one kind: "translation".
"""

BASE_URL = "https://gateway.jeedu.net"
FIND_SCHOOLS_URL = "/api/user/anonymousUser/findSchools"
GET_TOKEN_URL = "/api/auth/oauth/token"
GET_HW_LIST_URL = "/api/exam/studentApi/userTaskPage"
GET_TRANSLATION_HW_LIST_URL = "/api/exam/sentence/studentSentencePage"
GET_HW_DETAILS_URL = "/api/exam/studentApi/userTaskResult"
GET_HW_CONTENT_URL = "/api/exam/taskPaper"
GET_TRANSLATION_HW_CONTENT_URL = "/api/exam/sentence/selectSentenceQuestion"
LOAD_ANSWERS_CACHE_URL = "/api/exam/studentApi/loadCache"
SAVE_ANSWERS_CACHE_URL = "/api/exam/studentApi/saveCache"
SUBMIT_ANSWERS_URL = "/api/exam/studentApi/userTaskSubmit"
START_HW_URL = "/api/exam/studentApi/userTaskStart"
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
