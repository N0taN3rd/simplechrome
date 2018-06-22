from robber.explanation import Explanation
from robber.matchers.base import Base
from ..expected import expect

__all__ = ["Empty"]


class Empty(Base):
    """
    expect([]).to.be.empty()
    expect({}).to.be.empty()
    """

    def matches(self):
        try:
            return len(self.actual) == 0
        except TypeError:
            return False

    @property
    def explanation(self):
        return Explanation(self.actual, self.is_negative, "be empty")


expect.register("empty", Empty)
