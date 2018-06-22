from robber.explanation import Explanation
from robber.matchers.base import Base
from ..expected import expect

__all__ = ["Include"]


class Include(Base):
    """
    expect([]).to.be.empty()
    expect({}).to.be.empty()
    """

    def matcher(self):
        try:
            return len(self.actual) == 0
        except TypeError:
            return False

    @property
    def explanation(self):
        return Explanation(self.actual, self.is_negative, "be empty")


expect.register("include", Include)
