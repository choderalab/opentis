def savecache(func):
    def inner(self, obj, idx = None, *args, **kwargs):
        idx = self.index(obj, idx)
        # add logging here
        # print 'SAVE in', self.db, ':', idx
        if idx is not None:
            func(self, obj, idx, *args, **kwargs)

        # store the ID in the cache
        self.cache[idx] = obj
        if self.named and hasattr(obj, 'name') and obj.name != '':
            self.cache[obj.name] = obj

    return inner

def saveidentifiable(func):
    def inner(self, obj, idx=None, *args, **kwargs):
        if idx is None and hasattr(obj, 'identifier'):
            if not hasattr(obj,'json'):
                setattr(obj,'json',self.object_to_json(obj))

            find_idx = self.find_by_identifier(obj.identifier)
            if find_idx is not None:
                # found and does not need to be saved, but we will let this ensemble point to the storage
                # in case we want to save and need the idx
                obj.idx[self.storage] = find_idx
                self.cache[find_idx] = obj
                self.all_names[obj.identifier] = find_idx
            else:
                func(self, obj, idx, *args, **kwargs)
                # Finally register with the new idx in the identifier cache dict.
                new_idx = obj.idx[self.storage]
                self.all_names[obj.identifier] = new_idx
        else:
            func(self, obj, idx, *args, **kwargs)

    return inner

def loadcache(func):
    def inner(self, idx, *args, **kwargs):
        # TODO: Maybe this functionality should be in a separate function

        if type(idx) is not str and idx < 0:
            return None

        n_idx = idx

        if idx in self.cache:
            cc = self.cache[idx]
            if type(cc) is int:
                # here the cached value is actually only the index
                # so it still needs to be loaded with the given index
                # this happens when we want to load by name (str)
                # and we need to actually load it
                n_idx = cc
            else:
                # we have a real object (hopefully) and just return from cache
                return self.cache[idx]

        elif type(idx) is str:
            # we want to load by name and it was not in cache
            if self.named:
                # only do it, if we allow named objects
                if not self._names_loaded:
                    # this only has to happen once, since afterwards we keep track of the name_cache
                    # this name cache shares just the normal cache but stores indices instead of objects
                    self.update_name_cache()
                if idx in self.cache:
                    n_idx = self.cache[idx]
                else:
                    raise ValueError('str "' + idx + '" not found in storage')
            else:
                raise ValueError('str "' + idx + '" as indices are only allowed in named storage')

            n_idx = self.idx_from_name(idx)

        obj = func(self, n_idx, *args, **kwargs)

        if not hasattr(obj, 'idx'):
            obj.idx = {}

        obj.idx[self.storage] = n_idx
        self.cache[obj.idx[self.storage]] = obj

        if self.named and not hasattr(obj, 'name'):
            # get the name of the object
            setattr(obj, 'name', self.get_name(idx))

        if self.named and hasattr(obj, 'name') and obj.name != '':
            self.cache[obj.name] = obj

        return obj
    return inner

def loadidentifiable(func):
    def inner(self, idx=None, *args, **kwargs):
        if idx is not None and type(idx) is str:
            find_idx = self.find_by_identifier(idx)
            if find_idx is not None:
                # names id is found so load with normal id
                return func(self, find_idx, *args, **kwargs)
            else:
                # named id does not exist
                return None
        else:
            return func(self, idx, *args, **kwargs)

    return inner


def nestable(super_class):
    super_class.nestable = True
    return super_class


def storable(super_class):
    super_class.default_storage = None
    _base_cls_name = super_class.__name__

    def _init(self, *args, **kwargs):
        super_class._init(self, *args, **kwargs)

        if 'idx' in kwargs:
            self.idx = kwargs['idx']
        else:
            self.idx = dict()

        if 'storage' in kwargs:
            self.default_storage = kwargs['storage']

        super_class.base_cls_name = _base_cls_name

    def _save(self, storage=None):
        if storage is None:
            storage = self.default_storage
        storage.save(self)

    super_class._init = super_class.__init__
    super_class.__init__ = _init

    super_class.save = _save

    # register as a base_class for storable objects

    def __descendents__(clazz, cls=None):
        if cls is None:
            cls = super_class

        d = dict()
        d.update(_recurse_subclasses(cls))

        return d

    def _recurse_subclasses(cls):
        d = dict()
        for cls in super_class.__subclasses__():
            if cls is not object and cls is not None:
                d[cls.__name__] = cls
                subs = cls.__subclasses__()
                if len(subs) > 0:
                    d.update(super_class.subclass_dict(super_class, cls))
        return d

    super_class.__descendents__ = classmethod(__descendents__)

    return super_class