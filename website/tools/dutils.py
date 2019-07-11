
import datetime
import decimal

import django
from django.core.serializers.json import DjangoJSONEncoder
from django.utils.encoding import smart_str
from django.db.models.base import ModelBase
from django.template import loader
from django.template.context import RequestContext


class JSONEncoder(DjangoJSONEncoder):
    def default(self, o):
        if isinstance(o, datetime.date):
            return o.strftime('%Y-%m-%d')
        elif isinstance(o, datetime.datetime):
            return o.strftime('%Y-%m-%d %H:%M:%S')
        elif isinstance(o, decimal.Decimal):
            return str(o)
        elif isinstance(o, ModelBase):
            return '%s.%s' % (o._meta.app_label, o._meta.model_name)
        else:
            try:
                return super(JSONEncoder, self).default(o)
            except Exception:
                return smart_str(o)

from django.db.models.fields.related import ForeignObjectRel
RelatedObject = ForeignObjectRel


from django.apps import apps
get_model = apps.get_model



try:
    from django.db import transaction
    commit_on_success = transaction.commit_on_success
except:
    from django.db import transaction
    commit_on_success = transaction.atomic

try:
    from django.core.cache import get_cache
except:
    def get_cache(k):
        from django.core.cache import caches
        return caches[k]


from django.core.mail import send_mail # use: send_mail(subject, email, from_email, [user.email])

from django.utils.module_loading import import_module
from django.forms.utils import flatatt, ErrorDict
from django.forms.utils import ErrorDict
from django.forms.utils import ErrorList
from django.contrib.contenttypes.forms import BaseGenericInlineFormSet, generic_inlineformset_factory


def render_to_string(tpl, context_instance=None):
        return loader.render_to_string(tpl, context=get_context_dict(context_instance))


def get_context_dict(context):
    """
     Contexts in django version 1.9+ must be dictionaries. As website has a legacy with older versions of django,
    the function helps the transition by converting the [RequestContext] object to the dictionary when necessary.
    :param context: RequestContext
    :return: dict
    """
    if isinstance(context, RequestContext):
        ctx = {}
        list(map(ctx.update, context.dicts))
    else:
        ctx = context
    return ctx


class JsonErrorDict(ErrorDict):

    def __init__(self, errors, form):
        super(JsonErrorDict, self).__init__(errors)
        self.form = form

    def as_json(self):
        if not self:
            return ''
        return [{'id': self.form[k].auto_id if k != NON_FIELD_ERRORS else NON_FIELD_ERRORS, 'name': k, 'errors': v} for
                k, v in list(self.items())]



NON_FIELD_ERRORS = '__all__'
