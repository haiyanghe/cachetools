from __future__ import absolute_import

import collections
import time

from .cache import Cache

# Python 2 and 3 compatibility
if hasattr(dict(), "iteritems"):
    iteritems = lambda d, *args, **kwargs: d.iteritems(*args, **kwargs) # noqa
else:
    iteritems = lambda d, *args, **kwargs: iter(d.items(*args, **kwargs)) # noqa


class _Timer(object):

    def __init__(self, timer):
        self.__timer = timer
        self.__nesting = 0

    def __call__(self):
        if self.__nesting == 0:
            return self.__timer()
        else:
            return self.__time

    def __enter__(self):
        if self.__nesting == 0:
            self.__time = time = self.__timer()
        else:
            time = self.__time
        self.__nesting += 1
        return time

    def __exit__(self, *exc):
        self.__nesting -= 1

    def __reduce__(self):
        return _Timer, (self.__timer,)

    def __getattr__(self, name):
        return getattr(self.__timer, name)


class TTLCache(Cache):
    """
    LRU Cache implementation with per-item time-to-live (TTL) value.
    """

    def __init__(self, maxsize, ttl, timer=time.time, getsizeof=None):
        Cache.__init__(self, maxsize, getsizeof)
        self.__expiry_info = collections.OrderedDict()
        self.__order = collections.OrderedDict()
        self.__timer = _Timer(timer)
        self.__ttl = ttl

    def __contains__(self, key):
        try:
            expiry_time = self.__expiry_info[key]  # no reordering
        except KeyError:
            return False
        else:
            return (expiry_time >= self.__timer())

    def __getitem__(self, key, cache_getitem=Cache.__getitem__):
        try:
            expiry_time = self.__getexpiry(key)
        except KeyError:
            expired = False
        else:
            expired = expiry_time < self.__timer()
        if expired:
            return self.__missing__(key)
        else:
            return cache_getitem(self, key)

    def __setitem__(self, key, value, cache_setitem=Cache.__setitem__):
        with self.__timer as time:
            self.expire(time)
            cache_setitem(self, key, value)
            try:
                self.__getexpiry(key)
            except KeyError:
                self.__order[key] = None
            else:
                del self.__expiry_info[key]
            self.__expiry_info[key] = time + self.__ttl

    def __delitem__(self, key, cache_delitem=Cache.__delitem__):
        cache_delitem(self, key)
        del self.__order[key]
        expiry_time = self.__expiry_info.pop(key)
        if expiry_time < self.__timer():
            raise KeyError(key)

    def __iter__(self):
        for key, expiry_time in iteritems(self.__expiry_info):
            with self.__timer as time:
                if not (expiry_time < time):
                    yield key

    def __len__(self):
        time = self.__timer()
        count = len(self.__expiry_info)
        for key, expiry_time in iteritems(self.__expiry_info):
            if expiry_time < time:
                count -= 1
            else:
                break
        return count

    def __setstate__(self, state):
        self.__dict__.update(state)
        self.expire(self.__timer())

    def __repr__(self, cache_repr=Cache.__repr__):
        with self.__timer as time:
            self.expire(time)
            return cache_repr(self)

    @property
    def currsize(self):
        with self.__timer as time:
            self.expire(time)
            return super(TTLCache, self).currsize

    @property
    def timer(self):
        """The timer function used by the cache."""
        return self.__timer

    @property
    def ttl(self):
        """The time-to-live value of the cache's items."""
        return self.__ttl

    def expire(self, time=None):
        """Remove expired items from the cache."""
        if time is None:
            time = self.__timer()
        cache_delitem = Cache.__delitem__
        expiry_info = self.__expiry_info.copy()
        for key, expiry_time in iteritems(expiry_info):
            if expiry_time >= time:
                break
            cache_delitem(self, key)
            del self.__expiry_info[key]
            del self.__order[key]

    def clear(self):
        with self.__timer as time:
            self.expire(time)
            Cache.clear(self)

    def get(self, *args, **kwargs):
        with self.__timer:
            return Cache.get(self, *args, **kwargs)

    def pop(self, *args, **kwargs):
        with self.__timer:
            return Cache.pop(self, *args, **kwargs)

    def setdefault(self, *args, **kwargs):
        with self.__timer:
            return Cache.setdefault(self, *args, **kwargs)

    def popitem(self):
        """Remove and return the `(key, value)` pair least recently used that
        has not already expired.

        """
        with self.__timer as time:
            self.expire(time)
            try:
                key = next(iter(self.__order))
            except StopIteration:
                raise KeyError('%s is empty' % self.__class__.__name__)
            else:
                return (key, self.pop(key))

    if hasattr(collections.OrderedDict, 'move_to_end'):
        def __getexpiry(self, key): # noqa
            expiry_time = self.__expiry_info[key]
            self.__order.move_to_end(key)
            return expiry_time
    else:
        def __getexpiry(self, key): # noqa
            expiry_time = self.__expiry_info[key]
            del self.__order[key]
            self.__order[key] = None
            return expiry_time
