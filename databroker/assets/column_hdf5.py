import h5py
import json
import uuid
import os
import pandas as pd
import sqlite3
from pathlib import Path
import itertools
import numpy as np

# from .base_registry import BaseRegistry
from databroker.assets.base_registry import RegistryTemplate, RegistryMovingTemplate
from databroker.assets.sqlite import (ResourceCollection, ResourceUpdatesCollection,
                                      RegistryDatabase)
from databroker.assets.core import (resource_given_uid, insert_resource,
                                    update_resource, get_resource_history,
                                    doc_or_uid_to_uid, get_file_list)
from databroker.headersource.hdf5 import append
class DatumNotFound(Exception):
    ...

try:
    from types import SimpleNamespace
except ImportError:
    # LPy compatibility
    class SimpleNamespace:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

        def __repr__(self):
            keys = sorted(self.__dict__)
            items = ("{}={!r}".format(k, self.__dict__[k]) for k in keys)
            return "{}({})".format(type(self).__name__, ", ".join(items))

        def __eq__(self, other):
            return self.__dict__ == other.__dict__


def bulk_register_datum_table(datum_col, resource_col,
                              resource_uid, dkwargs_table,
                              validate):
    if validate:
        raise

    d_ids = [str(uuid.uuid4()) for j in range(len(dkwargs_table))]
    datum_ids = ['{}/{}'.format(resource_uid, d)
                 for d in d_ids]

    with h5py.File(f'{datum_col}/{resource_uid}.h5', 'w') as fout:
        for k, v in itertools.chain(
                dkwargs_table.items(),
                (('datum_id', np.array([d.encode('utf-8') for d in d_ids])),)):
            fout.create_dataset(k, (len(v),),
                                dtype=v.dtype,
                                data=v,
                                maxshape=(None, ),
                                chunks=True)

    return datum_ids


def retrieve(col, datum_id, datum_cache, get_spec_handler, logger):
    if '/' not in datum_id:
        raise DatumNotFound
    r_uid, _, d_uid = datum_id.partition('/')

    handler = get_spec_handler(r_uid)
    try:
        df = datum_cache[r_uid]
    except:
        with h5py.File(f'{col}/{r_uid}.h5', 'r') as fin:
            df = pd.DataFrame({k: fin[k] for k in fin})
            df['datum_id'] = df['datum_id'].str.decode('utf-8')
            df = df.set_index('datum_id')
        datum_cache[r_uid] = df

    return handler(**dict(df.loc[d_uid]))


def get_datum_by_res_gen(datum_col, resource_uid):
    # HACK!
    col = datum_col
    r_uid = resource_uid

    with h5py.File(f'{col}/{r_uid}.h5', 'r') as fin:
        df = pd.DataFrame({k: fin[k] for k in fin})
        df['datum_id'] = df['datum_id'].str.decode('utf-8')
        df = df.set_index('datum_id')

    for i, r in df.iterrows():
        yield {'datum_id': i,
               'resource': resource_uid,
               'datum_kwargs': dict(r)}


def resource_given_datum_id(col, datum_id, datum_cache, logger):
    r_uid, _, d_uid = datum_id.partition('/')
    return r_uid

def bulk_insert_datum(col, resource, datum_ids,
                      datum_kwarg_list):
    d_uids = bulk_register_datum_table(col, None,
                                       doc_or_uid_to_uid(resource),
                                       pd.DataFrame(datum_kwarg_list),
                                       False)

    return d_uids

def insert_datum(datum_col, resource, datum_id, datum_kwargs,
                 known_spec, resource_col):
    resource = doc_or_uid_to_uid(resource)
    p = Path(datum_col) / Path(f'{resource}.h5')
    if p.is_file():
        d_id = str(uuid.uuid4())
        d_uid = f'{resource}/{d_id}'
        with h5py.File(str(p), 'a') as fout:
            append(fout['datum_id'], [d_id.encode('utf-8')])
            for k, v in datum_kwargs.items():
                append(fout[k], [v])

    else:
        df = pd.DataFrame([datum_kwargs])
        d_uid, = bulk_register_datum_table(datum_col, resource_col,
                                           resource, df, False)
    return dict(resource=resource,
                datum_id=str(d_uid),
                datum_kwargs=dict(datum_kwargs))


api = SimpleNamespace(
    insert_resource=insert_resource,
    bulk_register_datum_table=bulk_register_datum_table,
    resource_given_uid=resource_given_uid,
    retrieve=retrieve,
    update_resource=update_resource,
    DatumNotFound=DatumNotFound,
    get_resource_history=get_resource_history,
    insert_datum=insert_datum,
    resource_given_datum_id=resource_given_datum_id,
    get_datum_by_res_gen=get_datum_by_res_gen,
    get_file_list=get_file_list,
    bulk_insert_datum=bulk_insert_datum)


class Registry(RegistryTemplate):

    _API_MAP = {1: api}
    REQ_CONFIG = ('dbpath',)

    def __init__(self, config):
        super().__init__(config)
        os.makedirs(self.config['dbpath'], exist_ok=True)
        # we are going to be caching dataframes so be
        # smaller!
        self._datum_cache.max_size = 100

        self.__db = None
        self.__resource_col = None
        self.__resource_update_col = None

    @property
    def _resource_col(self):
        return self.config['dbpath']

    @property
    def _datum_col(self):
        return self.config['dbpath']

    @property
    def _db(self):
        if self.__db is None:
            self.__db = RegistryDatabase(self.config['dbpath'] + '/r.sqlite')
        return self.__db

    @property
    def _resource_col(self):
        if self.__resource_col is None:
            self.__resource_col = ResourceCollection(self._db.conn)
        return self.__resource_col

    @property
    def _resource_update_col(self):
        if self.__resource_update_col is None:
            self.__resource_update_col = ResourceUpdatesCollection(
                self._db.conn)
        return self.__resource_update_col

    @property
    def DuplicateKeyError(self):
        return sqlite3.IntegrityError


class RegistryMoving(Registry, RegistryMovingTemplate):
    pass
