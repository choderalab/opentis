from openpathsampling.pathmovechange import PathMoveChange
from openpathsampling.netcdfplus import StorableObject, LoaderProxy, ObjectStore

class PathMoveChangeStore(ObjectStore):
    def __init__(self):
        super(PathMoveChangeStore, self).__init__(
            PathMoveChange,
            json=False
        )

        self._cached_all = False
        self.class_list = StorableObject.objects()

    def to_dict(self):
        return {}

    def _save(self, pathmovechange, idx):
        self.vars['samples'][idx] = pathmovechange.samples
        self.vars['subchanges'][idx] = pathmovechange.subchanges
        self.write('details', idx, pathmovechange)
        self.vars['mover'][idx] = pathmovechange.mover
        self.vars['cls'][idx] = pathmovechange.__class__.__name__

    def _load(self, idx):
        cls_name = self.vars['cls'][idx]

        cls = self.class_list[cls_name]
        obj = cls.__new__(cls)
        PathMoveChange.__init__(obj, mover=self.vars['mover'][idx])

        obj.samples = self.vars['samples'][idx]
        obj.subchanges = self.vars['subchanges'][idx]
        obj.details = self.vars['details'][idx]

        return obj

    def initialize(self, units=None):
        super(PathMoveChangeStore, self).initialize()

        # New short-hand definition
        self.create_variable('details', 'lazyobj.details')
        self.create_variable('mover', 'obj.pathmovers')
        self.create_variable('cls', 'str')

        self.create_variable('subchanges', 'obj.pathmovechanges',
                           dimensions=('...'),
                           chunksizes=(10240,)
                           )

        self.create_variable('samples', 'obj.samples',
                           dimensions=('...'),
                           chunksizes=(10240,)
                           )

    def all(self):
        self.cache_all()
        return self

    def cache_all(self):
        """Load all samples as fast as possible into the cache

        """
        if not self._cached_all:

            dummy = self[:]
            return

            idxs = range(len(self))

            cls_names = self.variables['cls'][:]
            samples_idxss = self.variables['samples'][:]
            subchanges_idxss = self.variables['subchanges'][:]
            mover_idxs = self.variables['mover'][:]
            details_idxs = self.variables['details'][:]

            [self._add_empty_to_cache(*v) for v in zip(
                idxs,
                cls_names,
                samples_idxss,
                mover_idxs,
                details_idxs)]

            [self._load_partial_subchanges(c, s) for c, s in zip(
                self,
                subchanges_idxss)]

            self._cached_all = True

    def _add_empty_to_cache(self, idx, cls_name, samples_idxs, mover_idx, details_idx):

        if idx not in self.cache:
            obj = self._load_partial_samples(cls_name, samples_idxs, mover_idx, details_idx)

            self._get_id(idx, obj)
            self.index[obj] = idx
            self.cache[idx] = obj

    def _load_partial_subchanges(self, obj, subchanges_idxs):
        if len(subchanges_idxs) > 0:
            obj.subchanges = [self.load(int(idx)) for idx in subchanges_idxs]

        return obj

    def _load_partial_samples(self, cls_name, samples_idxs, mover_idx, details_idx):
        cls = self.class_list[cls_name]
        obj = cls.__new__(cls)
        PathMoveChange.__init__(obj, mover=self.storage.pathmovers[mover_idx])

        if self.reference_by_uuid:
            samples_idxs = self.storage.to_uuid_chunks(samples_idxs)

        if len(samples_idxs) > 0:
            obj.samples = [self.storage.samples[idx] for idx in samples_idxs]

        obj.details = self.storage.details.proxy(details_idx)
        return obj
