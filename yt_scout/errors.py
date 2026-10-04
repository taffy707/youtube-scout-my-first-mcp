class ToolError(Exception):
    """An expected failure, reported to Claude as {"error": code, "message": message}."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message
