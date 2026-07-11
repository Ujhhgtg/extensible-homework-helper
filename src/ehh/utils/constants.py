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
    ("answers",): [
        "complete",
        "download",
        "fill_in",
        "fill_in_speaking",
        "generate",
        "generate_speaking",
        "download_from_paper",
        "submit",
    ],
    ("account",): ["login", "logout", "select_default", "add"],
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

# Word-guided Chinese->English translation, matching the 简练 sentence-task format
# where each item supplies a required word/phrase (and sometimes a grammar pattern)
# that MUST appear in the translation. Answers are graded by a teacher, so they must
# read like natural student work, not a machine gloss.
GENERATE_SENTENCE_TRANSLATION_PROMPT = """
You are an experienced Chinese high-school English teacher. Translate each Chinese \
sentence into accurate, natural English suitable for a strong senior-high student.

Hard rules for every item:
1. You MUST use the given "word" (the key word or phrase being tested). Use the exact \
word or a correct inflected form of it (e.g. change tense, number, or part of speech \
as grammar requires). Never omit it or swap in a synonym.
2. If a "pattern" is given, you MUST build the sentence around that grammatical \
structure (e.g. an it-cleft, inversion, a specific clause type). If "pattern" is \
empty, just translate naturally.
3. Convey the full meaning of the Chinese sentence faithfully — do not drop or add \
information.
4. Produce ONE correct, idiomatic English sentence per item. Use correct grammar, \
spelling, capitalization and end punctuation.
5. Do not copy any provided reference answer verbatim; write your own natural version \
while still obeying the rules above.

INPUT (JSON array; each item has index, word, pattern, question=Chinese sentence):
```
{questions}
```

Output format — a JSON array, index matching the input, e.g.:
```
[
    {
        "index": 1,
        "kind": "translation",
        "content": "It is said that all the songs at next week's concert are patriotic."
    }
    // ... one object per input item, in the same order
]
```

Output requirements:
1. NO MARKDOWN, NO CODE FENCES, NO COMMENTS — output ONLY the raw JSON array.
2. Exactly one object per input item, keeping the same index order.
3. "kind" is always "translation"; "content" is the English sentence only.
"""

BASE_URL = "https://gateway.jeedu.net"
FIND_SCHOOLS_URL = "/api/user/anonymousUser/findSchools"
GET_TOKEN_URL = "/api/auth/oauth/token"
GET_HW_LIST_URL = "/api/exam/studentApi/userTaskPage"
GET_TRANSLATION_HW_LIST_URL = "/api/exam/sentence/studentSentencePage"
GET_HW_DETAILS_URL = "/api/exam/studentApi/userTaskResult"
GET_HW_CONTENT_URL = "/api/exam/taskPaper"
GET_TRANSLATION_HW_CONTENT_URL = "/api/exam/sentence/selectSentenceQuestion"
SUBMIT_TRANSLATION_URL = "/api/exam/sentence/submitUserTextTask"
LOAD_ANSWERS_CACHE_URL = "/api/exam/studentApi/loadCache"
SAVE_ANSWERS_CACHE_URL = "/api/exam/studentApi/saveCache"
SUBMIT_ANSWERS_URL = "/api/exam/studentApi/userTaskSubmit"
START_HW_URL = "/api/exam/studentApi/userTaskStart"
UPLOAD_URL = "/api/base/upload"
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
