# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
WADL data model.
'''

import re

from pyrocko import guts
from pyrocko.guts import make_typed_list_class, String, StringChoice, List, \
    Int, Object, StringUnion, Bool, Defer

from pyrocko.io.io_common import FileLoadError

ResourceTypeList = make_typed_list_class(String)


guts_prefix = 'wadl'
guts_xmlns = 'http://wadl.dev.java.net/2009/02'

re_rmsite = re.compile(r'https?://[^/]+')
re_multisl = re.compile(r'/+')


def clean_path(p):
    p = re_rmsite.sub('', p)
    p = re_multisl.sub('/', p)
    if not p.startswith('/'):
        p = '/' + p

    return p


class HTTPMethods(StringChoice):
    choices = [
        'GET',
        'POST',
        'PUT',
        'HEAD',
        'DELETE']


UriList = make_typed_list_class(String)

StatusCodeList = make_typed_list_class(Int)


class ParamStyle(StringChoice):
    choices = [
        'plain',
        'query',
        'matrix',
        'header',
        'template']


class Doc(Object):
    xmltagname = 'doc'
    title = String.T(optional=True, xmlstyle='attribute')


class Method2(StringUnion):
    members = [HTTPMethods, String]


class Include(Object):
    xmltagname = 'include'
    href = String.T(optional=True, xmlstyle='attribute')
    doc_list = List.T(Doc.T())


class Option(Object):
    xmltagname = 'option'
    value = String.T(xmlstyle='attribute')
    media_type = String.T(optional=True, xmlstyle='attribute')
    doc_list = List.T(Doc.T())


class Link(Object):
    xmltagname = 'link'
    resource_type = String.T(
        optional=True, xmlstyle='attribute', xmltagname='resource_type')
    rel = String.T(optional=True, xmlstyle='attribute')
    rev = String.T(optional=True, xmlstyle='attribute')
    doc_list = List.T(Doc.T())


class Grammars(Object):
    xmltagname = 'grammars'
    doc_list = List.T(Doc.T())
    include_list = List.T(Include.T())


class DerefError(Exception):
    pass


class Element(Object):

    def __init__(self, *args, **kwargs):
        Object.__init__(self, *args, **kwargs)
        self._hyper = None

    def _update(self, hyper):
        self._hyper = hyper

        id_ = getattr(self, 'id', None)

        if id_:
            hyper[self.xmltagname][id_] = self

        for child in self.get_children():
            child._update(hyper)

    def get_children(self):
        raise NotImplementedError()

    def deref(self):
        if not self._hyper:
            raise Exception('Must call _update() before calling deref()')

        obj = self
        seen = set()
        while True:
            seen.add(obj)
            href = getattr(obj, 'href', None)
            if href:
                try:
                    obj = obj._hyper[obj.xmltagname][href.lstrip('#')]
                    if obj in seen:
                        raise DerefError('cyclic reference')

                except KeyError:
                    raise DerefError(href)

            else:
                return obj


class Param(Element):
    xmltagname = 'param'
    href = String.T(optional=True, xmlstyle='attribute')
    name = String.T(optional=True, xmlstyle='attribute')
    style = ParamStyle.T(optional=True, xmlstyle='attribute')
    id = String.T(optional=True, xmlstyle='attribute')
    type = String.T(default='xs:string', optional=True, xmlstyle='attribute')
    default = String.T(optional=True, xmlstyle='attribute')
    required = Bool.T(default='false', optional=True, xmlstyle='attribute')
    repeating = Bool.T(default='false', optional=True, xmlstyle='attribute')
    fixed = String.T(optional=True, xmlstyle='attribute')
    path = String.T(optional=True, xmlstyle='attribute')
    doc_list = List.T(Doc.T())
    option_list = List.T(Option.T())
    link = Link.T(optional=True)

    def describe(self, indent):
        return indent + self.name

    def get_children(self):
        return []


class Representation(Element):
    xmltagname = 'representation'
    id = String.T(optional=True, xmlstyle='attribute')
    element = String.T(optional=True, xmlstyle='attribute')
    media_type = String.T(optional=True, xmlstyle='attribute')
    href = String.T(optional=True, xmlstyle='attribute')
    profile = UriList.T(optional=True, xmlstyle='attribute')
    doc_list = List.T(Doc.T())
    param_list = List.T(Param.T())

    def get_children(self):
        return self.param_list


class Request(Element):
    xmltagname = 'request'
    doc_list = List.T(Doc.T())
    param_list = List.T(Param.T())
    representation_list = List.T(Representation.T())

    def iter_params(self):
        for param in self.param_list:
            param = param.deref()
            yield param

    def describe(self, indent):
        lines = []
        for param in self.iter_params():
            lines.append(param.describe(indent))

        return lines

    def get_children(self):
        return self.param_list + self.representation_list


class Response(Element):
    xmltagname = 'response'
    status = StatusCodeList.T(optional=True, xmlstyle='attribute')
    doc_list = List.T(Doc.T())
    param_list = List.T(Param.T())
    representation_list = List.T(Representation.T())

    def get_children(self):
        return self.param_list + self.representation_list


class Method(Element):
    xmltagname = 'method'
    id = String.T(optional=True, xmlstyle='attribute')
    name = String.T(optional=True, xmlstyle='attribute')
    href = String.T(optional=True, xmlstyle='attribute')
    doc_list = List.T(Doc.T())
    request = Request.T(optional=True)
    response_list = List.T(Response.T())

    def describe(self, indent):
        lines = [indent + self.name]
        if self.request:
            lines.extend(self.request.describe('  ' + indent))

        return lines

    def get_children(self):
        return ([self.request] if self.request else []) + self.response_list


class Resource(Element):
    xmltagname = 'resource'
    id = String.T(optional=True, xmlstyle='attribute')
    type = String.T(optional=True, xmlstyle='attribute')
    query_type = String.T(
        default='application/x-www-form-urlencoded',
        optional=True,
        xmlstyle='attribute')
    path = String.T(optional=True, xmlstyle='attribute')
    doc_list = List.T(Doc.T())
    param_list = List.T(Param.T())
    method_list = List.T(Method.T())
    resource_list = List.T(Defer('Resource.T'))

    def iter_resources(self):
        yield self.path, self
        for res in self.resource_list:
            yield self.path + '/' + res.path, res

    def iter_methods(self):
        for method in self.method_list:
            method = method.deref()
            yield method

    def describe(self, indent):
        lines = []
        for met in self.iter_methods():
            lines.extend(met.describe('  ' + indent))

        return lines

    def get_children(self):
        return self.param_list + self.method_list + self.resource_list


class Resources(Element):
    xmltagname = 'resources'
    base = String.T(optional=True, xmlstyle='attribute')
    doc_list = List.T(Doc.T())
    resource_list = List.T(Resource.T())

    def iter_resources(self):
        for res in self.resource_list:
            for p, sr in res.iter_resources():
                yield self.base + '/' + p, sr

    def get_children(self):
        return self.resource_list


class ResourceType(Element):
    xmltagname = 'resource_type'
    id = String.T(optional=True, xmlstyle='attribute')
    doc_list = List.T(Doc.T())
    param_list = List.T(Param.T())
    method_list = List.T(Method.T())
    resource_list = List.T(Resource.T())

    def get_children(self):
        return self.param_list + self.method_list + self.resource_list


class Application(Element):
    xmltagname = 'application'
    guessable_xmlns = [guts_xmlns]

    doc_list = List.T(Doc.T())
    grammars = Grammars.T(optional=True)
    resources_list = List.T(Resources.T())
    resource_type_list = List.T(ResourceType.T(xmltagname='resource_type'))
    method_list = List.T(Method.T())
    representation_list = List.T(Representation.T())
    param_list = List.T(Param.T())

    def get_children(self):
        return self.resources_list + self.resource_type_list \
            + self.method_list + self.representation_list \
            + self.param_list

    def update(self, force=False):
        if self._hyper is None or force:
            hyper = dict(
                resource_type={},
                resource={},
                method={},
                representation={},
                param={})

            self._update(hyper)

    def iter_resources(self):
        self.update()
        for rs in self.resources_list:
            for p, res in rs.iter_resources():
                yield clean_path(p), res

    def iter_requests(self):
        for res_path, res in self.iter_resources():
            for method in res.iter_methods():
                if method.request:
                    yield res_path, method.name, method.request

    def supported_param_names(self, path, method='GET'):
        path = clean_path(path)
        for res_path, method_name, request in self.iter_requests():
            if res_path == path and method_name == method:
                return [param.name for param in request.param_list]

    def describe(self, indent=''):
        lines = []
        for res_path, res in self.iter_resources():
            lines.append(indent + res_path)
            lines.extend(res.describe(indent))

        return lines

    def __str__(self):
        return '\n'.join(self.describe())


def load_xml(*args, **kwargs):
    wadl = guts.load_xml(*args, **kwargs)
    if not isinstance(wadl, Application):
        FileLoadError('Not a WADL file.')

    return wadl


if __name__ == '__main__':
    import os
    import sys
    import urllib.request

    if os.path.exists(sys.argv[1]):
        wadl = load_xml(filename=sys.argv[1])
    else:
        f = urllib.request.urlopen(sys.argv[1])
        wadl = load_xml(stream=f)

    print(wadl)
