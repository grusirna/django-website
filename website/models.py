import json

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.urls import reverse
from django.utils.translation import ugettext_lazy as _

from .tools.dutils import JSONEncoder

AUTH_USER_MODEL = getattr(settings, 'AUTH_USER_MODEL')


class UserSetting(models.Model):
    user = models.ForeignKey(AUTH_USER_MODEL, verbose_name='用户', on_delete=models.CASCADE)
    key = models.CharField('设置键', max_length=256)
    value = models.TextField('设置内容')

    def json_value(self):
        return json.loads(self.value)

    def set_json(self, obj):
        self.value = json.dumps(obj, cls=JSONEncoder, ensure_ascii=False)

    def __str__(self):
        return "%s%s设置" % (self.user, self.key)

    class Meta:
        verbose_name = '设置'
        verbose_name_plural = verbose_name


class UserComponent(models.Model):
    user = models.ForeignKey(AUTH_USER_MODEL, verbose_name='用户', on_delete=models.CASCADE)
    page_id = models.CharField('页', max_length=256)
    widget_type = models.CharField('类型', max_length=50)
    value = models.TextField('参数')
    explain = models.TextField('说明')

    def get_value(self):
        value = json.loads(self.value)
        value['id'] = self.id
        value['type'] = self.widget_type
        return value

    def set_value(self, obj):
        self.value = json.dumps(obj, cls=JSONEncoder, ensure_ascii=False)

    def save(self, *args, **kwargs):
        created = self.pk is None
        super(UserComponent, self).save(*args, **kwargs)
        if created:
            try:
                portal_pos = UserSetting.objects.get(
                    user=self.user, key="dashboard:%s:pos" % self.page_id)
                portal_pos.value = "%s,%s" % (self.pk, portal_pos.value) if portal_pos.value else self.pk
                portal_pos.save()
            except Exception:
                pass

    def __str__(self):
        return "%s%s组件" % (self.user, self.widget_type)

    class Meta:
        verbose_name = '组件'
        verbose_name_plural = verbose_name


class Viewmark(models.Model):
    title = models.CharField(_('Title'), max_length=128)
    user = models.ForeignKey(AUTH_USER_MODEL, verbose_name=_("user"), blank=True, null=True, on_delete=models.SET_NULL)
    url_name = models.CharField(_('Url Name'), max_length=64)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    query = models.CharField(_('Query String'), max_length=1000, blank=True)
    is_share = models.BooleanField(_('Is Shared'), default=False)

    @property
    def url(self):
        base_url = reverse(self.url_name)
        if self.query:
            base_url = base_url + '?' + self.query
        return base_url

    def __str__(self):
        return self.title

    class Meta:
        verbose_name = '视图'
        verbose_name_plural = verbose_name
