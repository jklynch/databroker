from __future__ import (absolute_import, division, print_function,
                        unicode_literals)
import tornado.web
import simplejson as json
import itertools
import six
from bson.objectid import ObjectId
from bson.json_util import dumps
__author__ = 'arkilic'


def _unpack_params(handler):
    """Unpacks the queries from the body of the header
    Parameters
    ----------
    handler: tornado.web.RequestHandler
        Handler for incoming request to collection

    Returns: dict
    -------
        Unpacked query in dict format.
    """
    if not isinstance(handler, tornado.web.RequestHandler):
        raise TypeError('Cannot unpack the query params. Handler required')
    query = json.loads(list(handler.request.arguments.keys())[0])
    return query


def _normalize_object_id(kwargs, key):
    """Ensure that an id is an ObjectId, not a string.

    ..warning: Does in-place mutation of the document
    """
    try:
        kwargs[key] = ObjectId(kwargs[key])
    except KeyError:
        # This key wasn't used by the query; that's fine.
        pass
    except TypeError:
        # This key was given a more complex query.
        pass
    # Database errors will still raise.

def _stringify_oid_fields(document):
    """ Fancy and explicit name
    Parameters
    ----------
    document:
    :return:
    """
    for k, v in six.iteritems(document):
        if type(v) is ObjectId:
            document[k] = str(v)




class Indexable(object):
    def __init__(self,it):
        self.it = iter(it)
        self.already_computed=[]
    def __iter__(self):
        for elt in self.it:
            self.already_computed.append(elt)
            yield elt
    def __getitem__(self,index):
        try:
            max_idx=index.stop
        except AttributeError:
            max_idx=index
        n=max_idx-len(self.already_computed)+1
        if n>0:
            self.already_computed.extend(itertools.islice(self.it,n))
        return self.already_computed[index]