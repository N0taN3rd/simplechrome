import pytest
from grappa import should

from simplechrome.errors import ElementHandleError, NetworkError
from .base_test import BaseChromeTest


class TestQueryObject(BaseChromeTest):
    @pytest.mark.asyncio
    async def test_query_objects(self):
        await self.goto_empty()
        await self.page.evaluate('() => window.set = new Set(["hello", "world"])')
        prototypeHandle = await self.page.evaluateHandle("() => Set.prototype")
        objectsHandle = await self.page.queryObjects(prototypeHandle)
        count = await self.page.evaluate("objects => objects.length", objectsHandle)
        count | should.be.equal.to(1)
        values = await self.page.evaluate(
            "objects => Array.from(objects[0].values())", objectsHandle
        )
        values | should.be.equal.to(["hello", "world"])

    @pytest.mark.asyncio
    async def test_query_objects_disposed(self):
        await self.goto_empty()
        prototypeHandle = await self.page.evaluateHandle(
            "() => HTMLBodyElement.prototype"
        )
        await prototypeHandle.dispose()
        with pytest.raises(ElementHandleError):
            await self.page.queryObjects(prototypeHandle)

    @pytest.mark.asyncio
    async def test_query_objects_primitive_value_error(self):
        await self.goto_empty()
        prototypeHandle = await self.page.evaluateHandle("() => 42")
        with pytest.raises(ElementHandleError):
            await self.page.queryObjects(prototypeHandle)


class TestJSHandle(BaseChromeTest):
    @pytest.mark.asyncio
    async def test_get_property(self):
        await self.goto_empty()
        handle1 = await self.page.evaluateHandle("() => ({one: 1, two: 2, three: 3})")
        handle2 = await handle1.getProperty("two")
        await handle2.jsonValue() | should.be.equal.to(2)

    @pytest.mark.asyncio
    async def test_json_value(self):
        await self.goto_empty()
        handle1 = await self.page.evaluateHandle('() => ({foo: "bar"})')
        json = await handle1.jsonValue()
        json | should.be.equal.to({"foo": "bar"})

    @pytest.mark.asyncio
    async def test_json_date_fail(self):
        await self.goto_empty()
        handle = await self.page.evaluateHandle(
            '() => new Date("2017-09-26T00:00:00.000Z")'
        )
        json = await handle.jsonValue()
        json | should.be.equal.to({})

    @pytest.mark.asyncio
    async def test_json_circular_object_error(self):
        await self.goto_empty()
        windowHandle = await self.page.evaluateHandle("window")
        with pytest.raises(NetworkError) as cm:
            await windowHandle.jsonValue()
        str(cm.value) | should.be.equal.to(
            "Protocol Error (Runtime.callFunctionOn): Object reference chain is too long"
        )

    @pytest.mark.asyncio
    async def test_get_properties(self):
        await self.goto_empty()
        handle1 = await self.page.evaluateHandle('() => ({foo: "bar"})')
        properties = await handle1.getProperties()
        foo = properties.get("foo")
        foo | should.not_be.none
        await foo.jsonValue() | should.be.equal.to("bar")

    @pytest.mark.asyncio
    async def test_return_non_own_properties(self):
        await self.goto_empty()
        aHandle = await self.page.evaluateHandle(
            """() => {
            class A {
                constructor() {
                    this.a = '1';
                }
            }
            class B extends A {
                constructor() {
                    super();
                    this.b = '2';
                }
            }
            return new B();
        }"""
        )
        properties = await aHandle.getProperties()
        await properties.get("a").jsonValue() | should.be.equal.to("1")
        await properties.get("b").jsonValue() | should.be.equal.to("2")

    @pytest.mark.asyncio
    async def test_as_element(self):
        await self.goto_empty()
        aHandle = await self.page.evaluateHandle("() => document.body")
        element = aHandle.asElement()
        element | should.not_be.none

    @pytest.mark.asyncio
    async def test_as_element_non_element(self):
        await self.goto_empty()
        aHandle = await self.page.evaluateHandle("() => 2")
        aHandle.asElement() | should.be.none

    @pytest.mark.asyncio
    async def test_as_element_text_node(self):
        await self.goto_empty()
        await self.page.setContent("<div>ee!</div>")
        aHandle = await self.page.evaluateHandle(
            '() => document.querySelector("div").firstChild'
        )
        element = aHandle.asElement()
        element | should.not_be.none

        await self.page.evaluate(
            "(e) => e.nodeType === HTMLElement.TEXT_NODE", element
        ) | should.not_be.none

    @pytest.mark.asyncio
    async def test_to_string_number(self):
        await self.goto_empty()
        handle = await self.page.evaluateHandle("() => 2")
        handle.toString() | should.be.equal.to("JSHandle:2")

    @pytest.mark.asyncio
    async def test_to_string_str(self):
        await self.goto_empty()
        handle = await self.page.evaluateHandle('() => "a"')
        handle.toString() | should.be.equal.to("JSHandle:a")

    @pytest.mark.asyncio
    async def test_to_string_complicated_object(self):
        await self.goto_empty()
        handle = await self.page.evaluateHandle("() => window")
        handle.toString() | should.be.equal.to("JSHandle@object")
