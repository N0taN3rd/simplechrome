from typing import (
    Any,
    Awaitable,
    Dict,
    Generator,
    List,
    Optional,
    TYPE_CHECKING,
    Tuple,
    Union,
)

from ._typings import Number, SlotsT

if TYPE_CHECKING:
    from .frame_manager import Frame, FrameManager

__all__ = ["FrameResourceTree", "FrameResource"]


class FrameResource:
    __slots__: SlotsT = ["__weakref__", "_frame", "_frameResourceInfo", "_frameManager"]

    def __init__(
        self, frameResourceInfo: Dict, frame: "Frame", frameManager: "FrameManager"
    ) -> None:
        """Initialize a new instance of FrameResource

        :param frameResourceInfo: The CDP frame resource info
        :param frame: The id of the frame this resource is from
        :param frameManager: The frame manager for the page this resource's frame came from
        """
        self._frame: "Frame" = frame
        self._frameResourceInfo: Dict = frameResourceInfo
        self._frameManager: "FrameManager" = frameManager

    @property
    def url(self) -> str:
        """Resource URL"""
        return self._frameResourceInfo.get("url")

    @property
    def type(self) -> str:
        """Type of this resource"""
        return self._frameResourceInfo.get("type")

    @property
    def mimeType(self) -> str:
        """Resource mimeType as determined by the browser"""
        return self._frameResourceInfo.get("mimeType")

    @property
    def lastModified(self) -> Optional[Number]:
        """last-modified timestamp as reported by server"""
        return self._frameResourceInfo.get("lastModified")

    @property
    def contentSize(self) -> Optional[Number]:
        """Resource content size"""
        return self._frameResourceInfo.get("contentSize")

    @property
    def failed(self) -> Optional[bool]:
        """True if the resource failed to load"""
        return self._frameResourceInfo.get("contentSize")

    @property
    def canceled(self) -> Optional[bool]:
        """True if the resource was canceled during loading"""
        return self._frameResourceInfo.get("canceled")

    def getContent(self) -> Awaitable[Dict[str, Union[str, bool]]]:
        """Retrieve the contents of this frame resource"""
        return self._frameManager.getFrameResourceContent(self._frame.id, self.url)

    @property
    def as_dict(self) -> Dict:
        return dict(frameId=self._frame.id, **self._frameResourceInfo)

    def __str__(self) -> str:
        return f"FrameResource(url={self.url}, type={self.type}, frame={self._frame})"

    def __repr__(self) -> str:
        return self.__str__()


class FrameResourceTree:
    __slots__: SlotsT = [
        "__weakref__",
        "_children",
        "_frameManager",
        "_frame",
        "_resources",
        "_resourceTree",
    ]

    def __init__(self, resourceTree: Dict, frameManager: "FrameManager") -> None:
        """Initialize a new instance of FrameResourceTree

        :param resourceTree: Information about the Frame hierarchy along with their cached resources
        :param frameManager: Client instance used to communicate with the remote browser
        """
        self._frameManager: "FrameManager" = frameManager
        self._resourceTree: Dict = resourceTree
        self._frame: "Frame" = None
        self._resources: List[FrameResource] = []
        self._children: List[FrameResourceTree] = []
        self._build_tree()

    @property
    def raw_tree(self) -> Dict:
        return self._resourceTree

    @property
    def children(self) -> List["FrameResourceTree"]:
        return self._children

    @property
    def resources(self) -> List[FrameResource]:
        return self._resources

    @property
    def as_dict(self) -> Dict:
        return self._resourceTree

    def walk_tree(self) -> Generator[Tuple[List[FrameResource], "Frame"], Any, None]:
        q = [self]
        add_to_q = q.append
        pop_q = q.pop
        while 1:
            if not q:
                break
            next_frame_tree = pop_q(0)
            if next_frame_tree is None:
                break
            yield next_frame_tree._resources, next_frame_tree._frame,
            for children in next_frame_tree._children:
                add_to_q(children)

    def _build_tree(self) -> None:
        frame = self._frameManager.frame(self._resourceTree["frame"]["id"])
        self._frame = frame
        resources = self._resourceTree["resources"]
        add_resource = self._resources.append
        frameman = self._frameManager
        for resource in resources:
            add_resource(FrameResource(resource, frame, frameman))
        children = self._resourceTree.get("childFrames")
        if children is None:
            return
        add_child = self._children.append
        for child in children:
            add_child(FrameResourceTree(child, frameman))

    def __str__(self) -> str:
        return f"FrameResourceTree(resources={self.resources}, children={self.children}, frame={self._frame})"

    def __repr__(self) -> str:
        return self.__str__()
