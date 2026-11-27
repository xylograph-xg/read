"""Shared paths for parsed evidence and generated cards (pages are one-based)."""
import hashlib
import json


def equation_identity(page, bbox):
    geometry=[round(float(value),2) for value in bbox]
    return hashlib.sha256(json.dumps([page,geometry],separators=(',',':')).encode()).hexdigest()[:16]


def equation_folder(number, page, identity=''):
    if number is not None:return f'Eq_{number}_p{page}'+('_'+identity if identity else '')
    return f'Eq_p{page}'+('_'+identity if identity else '')
