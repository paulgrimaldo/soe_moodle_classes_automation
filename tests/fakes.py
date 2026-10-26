from copy import deepcopy
from uuid import uuid4


class FakeNotion:
    def __init__(self):
        self.pages, self.blocks, self.child_map = {}, {}, {}
        self.writes = 0

    def add_page(self, parent=None, title="MLOps"):
        identifier = str(uuid4())
        self.pages[identifier] = {"id": identifier, "parent": {"type": "page_id", "page_id": parent},
            "url": f"https://www.notion.so/{identifier}", "properties": {"title": {"type": "title",
            "title": [{"text": {"content": title}}]}}}
        self.child_map[identifier] = []
        if parent:
            self.blocks[identifier] = {"id": identifier, "type": "child_page", "child_page": {"title": title}}
            self.child_map[parent].append(identifier)
        return identifier

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass

    async def page(self, identifier):
        return deepcopy(self.pages[identifier])

    async def block(self, identifier):
        return deepcopy(self.blocks[identifier])

    async def children(self, identifier):
        return [deepcopy(self.blocks[i]) for i in self.child_map[identifier]]

    async def search(self, title):
        return list(deepcopy(self.pages).values())

    async def create_week(self, parent, week):
        self.writes += 1
        return await self.page(self.add_page(parent, f"Semana {week}"))

    def create_block(self, block):
        identifier = str(uuid4())
        obj = deepcopy(block)
        nested = obj[obj["type"]].pop("children", [])
        obj.update(id=identifier, has_children=bool(nested))
        self.blocks[identifier] = obj
        self.child_map[identifier] = [self.create_block(child) for child in nested]
        return identifier

    async def append(self, parent, blocks, *, after=None, start=False):
        self.writes += 1
        index = 0 if start else len(self.child_map[parent])
        if after:
            index = self.child_map[parent].index(after) + 1
        ids = [self.create_block(b) for b in blocks]
        self.child_map[parent][index:index] = ids
        return [deepcopy(self.blocks[i]) for i in ids]

    async def delete(self, identifier):
        self.writes += 1
        for children in self.child_map.values():
            if identifier in children:
                children.remove(identifier)
        self.blocks[identifier]["in_trash"] = True
