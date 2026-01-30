from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.validation import Validator, ValidationError
from prompt_toolkit.document import Document


# Powered by Google Gemini
class ReplCompleter(Completer):
    def __init__(self, completion_map):
        self.completion_map = completion_map

    def get_completions(self, document: Document, complete_event):
        # Get text before the cursor
        text_before_cursor = document.text_before_cursor

        # Split input into words to determine context
        words = text_before_cursor.split()

        # Logic to determine 'context' (previous words) and 'current_word' (being typed)
        if text_before_cursor.endswith(" "):
            # If the user typed a space, they are ready for the next word.
            # Context is all words typed so far.
            context = tuple(words)
            current_word = ""
        else:
            if not words:
                # Empty input
                context = ()
                current_word = ""
            else:
                # User is currently typing the last word in the list.
                # Context is everything up to that last word.
                context = tuple(words[:-1])
                current_word = words[-1]

        # Fetch valid completions for this context
        # If the context doesn't exist in the map, we return an empty list
        suggestions = self.completion_map.get(context, [])

        # Yield completions that match the current partial word
        for option in suggestions:
            if option.startswith(current_word):
                # start_position is negative length of the characters to replace
                yield Completion(option, start_position=-len(current_word))


def prompt_for_yn(session: PromptSession, message: str) -> bool:
    while True:
        response = session.prompt(message)

        if "yes".startswith(response.lower()):
            return True
        elif "no".startswith(response.lower()):
            return False
