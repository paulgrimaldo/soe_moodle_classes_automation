class StageError(Exception):
    def __init__(self, code: str, *, retryable: bool = False, review: bool = False):
        super().__init__(code)
        self.code, self.retryable, self.review = code, retryable, review


class Conflict(StageError):
    def __init__(self, code: str):
        super().__init__(code, review=True)
