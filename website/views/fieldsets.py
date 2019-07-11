import math

from crispy_forms import layout
from crispy_forms.layout import Div, Field, Column


class Row(Div):

    def __init__(self, *fields, **kwargs):
        css_class = 'form-inline form-group'
        new_fields = [self.convert_field(f, len(fields)) for f in fields]
        super(Row, self).__init__(css_class=css_class, *new_fields, **kwargs)

    def convert_field(self, f, counts):
        col_class = "col-sm-%d" % int(math.ceil(12 / counts))
        if not (isinstance(f, Field) or issubclass(f.__class__, Field)):
            f = layout.Field(f)
        if f.wrapper_class:
            f.wrapper_class += " %s" % col_class
        else:
            f.wrapper_class = col_class
        return f


class Col(Column):

    def __init__(self, id, *fields, **kwargs):
        css_class = ['column', 'form-column', id, 'col col-sm-%d' %
                     kwargs.get('span', 6)]
        if kwargs.get('horizontal'):
            css_class.append('form-horizontal')
        super(Col, self).__init__(css_class=' '.join(css_class), *
        fields, **kwargs)


class Main(Column):
    css_class = "column form-column main col col-sm-9 form-horizontal"


class Side(Column):
    css_class = "column form-column sidebar col col-sm-3"


class Container(Div):
    css_class = "form-container row clearfix"