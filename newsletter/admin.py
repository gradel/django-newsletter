from __future__ import unicode_literals

import logging
logger = logging.getLogger(__name__)

import six

from django.db import models

from django.conf import settings
from django.conf.urls import url

from django.contrib import admin, messages
from django.contrib.sites.models import Site

from django.core import serializers
from django.core.exceptions import PermissionDenied
from django.core.urlresolvers import reverse

from django.http import HttpResponse, HttpResponseRedirect, Http404

from django.shortcuts import render

from django.utils.html import format_html
from django.utils.text import force_text
from django.utils.translation import ugettext as _, ungettext
from django.utils.formats import date_format

from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.i18n import javascript_catalog

from easy_thumbnails.files import get_thumbnailer
from sorl.thumbnail.admin import AdminImageMixin

from .models import (
    Newsletter, Subscription, Article, Message, Submission
)

from django.utils.timezone import now

from .admin_forms import (
    SubmissionAdminForm, SubscriptionAdminForm, ImportForm, ConfirmForm,
    ArticleFormSet
)
from .admin_utils import ExtendibleModelAdminMixin, make_subscription

from .compat import get_context

from .settings import newsletter_settings

from mezzanine.core.admin import TabularDynamicInlineAdmin

from utils.models import ArticleImageItem


# Contsruct URL's for icons
ICON_URLS = {
    'yes': '%snewsletter/admin/img/icon-yes.gif' % settings.STATIC_URL,
    'wait': '%snewsletter/admin/img/waiting.gif' % settings.STATIC_URL,
    'submit': '%snewsletter/admin/img/submitting.gif' % settings.STATIC_URL,
    'no': '%snewsletter/admin/img/icon-no.gif' % settings.STATIC_URL
}


class NewsletterAdmin(admin.ModelAdmin):
    list_display = (
        'title', 'admin_subscriptions', 'admin_messages', 'admin_submissions'
    )
    prepopulated_fields = {'slug': ('title',)}

    """ List extensions """
    def _admin_url(self, obj, model, text):
        url = reverse('admin:%s_%s_changelist' %
                      (model._meta.app_label, model._meta.model_name),
                      current_app=self.admin_site.name)

        return format_html(
            '<a href="{}?newsletter__id={}">{}</a>', url, obj.id, text
        )

    def admin_messages(self, obj):
        return self._admin_url(obj, Message, _("Messages"))
    admin_messages.short_description = ''

    def admin_subscriptions(self, obj):
        return self._admin_url(obj, Subscription, _("Subscriptions"))
    admin_subscriptions.short_description = ''

    def admin_submissions(self, obj):
        return self._admin_url(obj, Submission, _("Submissions"))
    admin_submissions.short_description = ''


class NewsletterAdminLinkMixin(object):
    def admin_newsletter(self, obj):
        opts = Newsletter._meta
        newsletter = obj.newsletter
        url = reverse('admin:%s_%s_change' % (opts.app_label, opts.model_name),
                      args=(newsletter.id,), current_app=self.admin_site.name)

        return format_html('<a href="{}">{}</a>', url, newsletter)
    admin_newsletter.short_description = _('newsletter')


class SubmissionAdmin(NewsletterAdminLinkMixin, ExtendibleModelAdminMixin,
                      admin.ModelAdmin):
    form = SubmissionAdminForm
    list_display = (
        'admin_message', 'admin_newsletter', 'admin_publish_date', 'publish',
        'admin_status_text', 'admin_status'
    )
    date_hierarchy = 'publish_date'
    list_filter = ('newsletter', 'publish', 'sent')
    save_as = True
    filter_horizontal = ('subscriptions',)

    """ List extensions """
    def admin_message(self, obj):
        return format_html('<a href="{}/">{}</a>', obj.id, obj.message.title)
    admin_message.short_description = _('submission')

    def admin_publish_date(self, obj):
        if obj.publish_date:
            return date_format(obj.publish_date, 'DATETIME_FORMAT')
        else:
            return ''
    admin_publish_date.short_description = _("publish date")

    def admin_status(self, obj):
        if obj.prepared:
            if obj.sent:
                return format_html(
                    '<img src="{}" width="10" height="10" alt="{}"/>',
                    ICON_URLS['yes'], self.admin_status_text(obj)
                )
            else:
                if obj.publish_date > now():
                    return format_html(
                        '<img src="{}" width="10" height="10" alt="{}"/>',
                        ICON_URLS['wait'], self.admin_status_text(obj)
                    )
                else:
                    return format_html(
                        '<img src="{}" width="12" height="12" alt="{}"/>',
                        ICON_URLS['wait'], self.admin_status_text(obj)
                    )
        else:
            return format_html(
                '<img src="{}" width="10" height="10" alt="{}"/>',
                ICON_URLS['no'], self.admin_status_text(obj)
            )
    admin_status.short_description = ''

    def admin_status_text(self, obj):
        if obj.prepared:
            if obj.sent:
                return _("Sent.")
            else:
                if obj.publish_date > now():
                    return _("Delayed submission.")
                else:
                    return _("Submitting.")
        else:
            return _("Not sent.")
    admin_status_text.short_description = _('Status')

    """ Views """
    def submit(self, request, object_id):
        submission = self._getobj(request, object_id)

        if submission.sent or submission.prepared:
            messages.info(request, _("Submission already sent."))
            change_url = reverse(
                'admin:newsletter_submission_change', args=[object_id]
            )
            return HttpResponseRedirect(change_url)

        submission.prepared = True
        submission.save()

        messages.info(request, _("Your submission is being sent."))

        changelist_url = reverse('admin:newsletter_submission_changelist')
        return HttpResponseRedirect(changelist_url)

    """ URLs """
    def get_urls(self):
        urls = super(SubmissionAdmin, self).get_urls()

        my_urls = [
            url(
                r'^(.+)/submit/$',
                self._wrap(self.submit),
                name=self._view_name('submit')
            )
        ]

        return my_urls + urls


StackedInline = admin.StackedInline
if (
        newsletter_settings.RICHTEXT_WIDGET
        and newsletter_settings.RICHTEXT_WIDGET.__name__ == "ImperaviWidget"
):
    # Imperavi works a little differently
    # It's not just a field, it's also a media class and a method.
    # To avoid complications, we reuse ImperaviStackedInlineAdmin
    try:
        from imperavi.admin import ImperaviStackedInlineAdmin
        StackedInline = ImperaviStackedInlineAdmin
    except ImportError:
        # Log a warning when import fails as to aid debugging.
        logger.warning(
            'Error importing ImperaviStackedInlineAdmin. '
            'Imperavi WYSIWYG text editor might not work.'
        )


class ArticleInline(AdminImageMixin, StackedInline):
    model = Article
    extra = 2
    formset = ArticleFormSet
    readonly_fields = ["get_edit_link", 'display_images']
    fieldsets = (
        (None, {
            'fields': ('section_heading', 'title', 'text', 'display_images', "get_edit_link")
        }),
        (_('Optional'), {
            'fields': ('sortorder',),
            'classes': ('collapse',)
        }),
    )

    if newsletter_settings.RICHTEXT_WIDGET:
        formfield_overrides = {
            models.TextField: {'widget': newsletter_settings.RICHTEXT_WIDGET},
        }

    def get_edit_link(self, obj=None):
        if obj.pk:  # if object has already been saved and has a primary key, show link to it
            url = reverse('admin:%s_%s_change' % (obj._meta.app_label, obj._meta.model_name), args=[force_text(obj.pk)])
            return """<a href="{url}">{text}</a>""".format(
                url=url,
                text=_("Artikel einzeln editieren (um Bilder hinzuzufügen)") % obj._meta.verbose_name,
            )
        return _("(sichern und weiter bearbeiten um den Link zur Einzelbearbeitung zu erzeugen)")
    get_edit_link.short_description = _("Artikel-Link")
    get_edit_link.allow_tags = True

    def display_images(self, obj=None):
        if obj.article_images.all():
            urls = []
            for image in obj.article_images.all():
                nailer = get_thumbnailer(image.image)
                thumb = nailer.get_thumbnail({'crop': True, 'size': (50, 50)})
                urls.append(thumb.url)
            image_links = ['<img src="%s" />' % url for url in urls]
            return ''.join(image_links)
        return 'keine Bilder'
    display_images.short_description = _("Bilder")
    display_images.allow_tags = True


class MessageAdmin(NewsletterAdminLinkMixin, ExtendibleModelAdminMixin,
                   admin.ModelAdmin):
    save_as = True
    list_display = (
        'admin_title', 'admin_newsletter', 'admin_preview', 'date_create',
        'date_modify'
    )
    list_filter = ('newsletter', )
    date_hierarchy = 'date_create'
    prepopulated_fields = {'slug': ('title',)}

    inlines = [ArticleInline, ]

    """ List extensions """
    def admin_title(self, obj):
        return format_html('<a href="{}/">{}</a>', obj.id, obj.title)
    admin_title.short_description = _('message')

    def admin_preview(self, obj):
        url = reverse('admin:' + self._view_name('preview'), args=(obj.id,),
                      current_app=self.admin_site.name)
        return format_html('<a href="{}">{}</a>', url, _("Preview"))
    admin_preview.short_description = ''

    """ Views """
    def preview(self, request, object_id):
        return render(
            request,
            "admin/newsletter/message/preview.html",
            {'message': self._getobj(request, object_id)},
        )

    @xframe_options_sameorigin
    def preview_html(self, request, object_id):
        message = self._getobj(request, object_id)

        if not message.html_template:
            raise Http404(_(
                'No HTML template associated with the newsletter this '
                'message belongs to.'
            ))

        c = get_context({'message': message,
                         'site': Site.objects.get_current(),
                         'newsletter': message.newsletter,
                         'date': now(),
                         'STATIC_URL': settings.STATIC_URL,
                         'MEDIA_URL': settings.MEDIA_URL})

        return HttpResponse(message.html_template.render(c))

    @xframe_options_sameorigin
    def preview_text(self, request, object_id):
        message = self._getobj(request, object_id)

        c = get_context({
            'message': message,
            'site': Site.objects.get_current(),
            'newsletter': message.newsletter,
            'date': now(),
            'STATIC_URL': settings.STATIC_URL,
            'MEDIA_URL': settings.MEDIA_URL
        }, autoescape=False)

        return HttpResponse(
            message.text_template.render(c),
            content_type='text/plain'
        )

    def submit(self, request, object_id):
        submission = Submission.from_message(self._getobj(request, object_id))

        change_url = reverse(
            'admin:newsletter_submission_change', args=[submission.id])

        return HttpResponseRedirect(change_url)

    def subscribers_json(self, request, object_id):
        message = self._getobj(request, object_id)

        json = serializers.serialize(
            "json", message.newsletter.get_subscriptions(), fields=()
        )
        return HttpResponse(json, content_type='application/json')

    """ URLs """
    def get_urls(self):
        urls = super(MessageAdmin, self).get_urls()

        my_urls = [
            url(r'^(.+)/preview/$',
                self._wrap(self.preview),
                name=self._view_name('preview')),
            url(r'^(.+)/preview/html/$',
                self._wrap(self.preview_html),
                name=self._view_name('preview_html')),
            url(r'^(.+)/preview/text/$',
                self._wrap(self.preview_text),
                name=self._view_name('preview_text')),
            url(r'^(.+)/submit/$',
                self._wrap(self.submit),
                name=self._view_name('submit')),
            url(r'^(.+)/subscribers/json/$',
                self._wrap(self.subscribers_json),
                name=self._view_name('subscribers_json')),
        ]

        return my_urls + urls


class SubscriptionAdmin(NewsletterAdminLinkMixin, ExtendibleModelAdminMixin,
                        admin.ModelAdmin):
    form = SubscriptionAdminForm
    list_display = (
        'name', 'email', 'admin_newsletter', 'admin_subscribe_date',
        'admin_unsubscribe_date', 'admin_status_text', 'admin_status'
    )
    list_display_links = ('name', 'email')
    list_filter = (
        'newsletter', 'subscribed', 'unsubscribed', 'subscribe_date'
    )
    search_fields = (
        'name_field', 'email_field', 'user__first_name', 'user__last_name',
        'user__email'
    )
    readonly_fields = (
        'ip', 'subscribe_date', 'unsubscribe_date', 'activation_code'
    )
    date_hierarchy = 'subscribe_date'
    actions = ['make_subscribed', 'make_unsubscribed']
    exclude = ['unsubscribed']

    """ List extensions """
    def admin_status(self, obj):
        img_tag = '<img src="{}" width="10" height="10" alt="{}"/>'
        alt_txt = self.admin_status_text(obj)
        if obj.unsubscribed:
            return format_html(img_tag, ICON_URLS['no'], alt_txt)

        if obj.subscribed:
            return format_html(img_tag, ICON_URLS['yes'], alt_txt)
        else:
            return format_html(img_tag, ICON_URLS['wait'], alt_txt)
    admin_status.short_description = ''

    def admin_status_text(self, obj):
        if obj.subscribed:
            return _("Subscribed")
        elif obj.unsubscribed:
            return _("Unsubscribed")
        else:
            return _("Unactivated")
    admin_status_text.short_description = _('Status')

    def admin_subscribe_date(self, obj):
        if obj.subscribe_date:
            return date_format(obj.subscribe_date)
        else:
            return ''
    admin_subscribe_date.short_description = _("subscribe date")

    def admin_unsubscribe_date(self, obj):
        if obj.unsubscribe_date:
            return date_format(obj.unsubscribe_date)
        else:
            return ''
    admin_unsubscribe_date.short_description = _("unsubscribe date")

    """ Actions """
    def make_subscribed(self, request, queryset):
        rows_updated = queryset.update(subscribed=True)
        self.message_user(
            request,
            ungettext(
                "%d user has been successfully subscribed.",
                "%d users have been successfully subscribed.",
                rows_updated
            ) % rows_updated
        )
    make_subscribed.short_description = _("Subscribe selected users")

    def make_unsubscribed(self, request, queryset):
        rows_updated = queryset.update(subscribed=False)
        self.message_user(
            request,
            ungettext(
                "%d user has been successfully unsubscribed.",
                "%d users have been successfully unsubscribed.",
                rows_updated
            ) % rows_updated
        )
    make_unsubscribed.short_description = _("Unsubscribe selected users")

    """ Views """
    def subscribers_import(self, request):
        if not request.user.has_perm('newsletter.add_subscription'):
            raise PermissionDenied()
        if request.POST:
            form = ImportForm(request.POST, request.FILES)
            if form.is_valid():
                request.session['addresses'] = form.get_addresses()
                request.session['newsletter_pk'] = \
                    form.cleaned_data['newsletter'].pk

                confirm_url = reverse(
                    'admin:newsletter_subscription_import_confirm'
                )
                return HttpResponseRedirect(confirm_url)
        else:
            form = ImportForm()

        return render(
            request,
            "admin/newsletter/subscription/importform.html",
            {'form': form},
        )

    def subscribers_import_confirm(self, request):
        # If no addresses are in the session, start all over.

        if 'addresses' not in request.session:
            import_url = reverse('admin:newsletter_subscription_import')
            return HttpResponseRedirect(import_url)

        addresses = request.session['addresses']
        newsletter = Newsletter.objects.get(
            pk=request.session['newsletter_pk']
        )

        logger.debug('Confirming addresses: %s', addresses)

        if request.POST:
            form = ConfirmForm(request.POST)
            if form.is_valid():
                try:
                    for email, name in six.iteritems(addresses):
                        address_inst = make_subscription(
                            newsletter, email, name
                        )
                        address_inst.save()
                finally:
                    del request.session['addresses']
                    del request.session['newsletter_pk']

                messages.success(
                    request,
                    ungettext(
                        "%d subscription has been successfully added.",
                        "%d subscriptions have been successfully added.",
                        len(addresses)
                    ) % len(addresses)
                )

                changelist_url = reverse(
                    'admin:newsletter_subscription_changelist'
                )
                return HttpResponseRedirect(changelist_url)
        else:
            form = ConfirmForm()

        return render(
            request,
            "admin/newsletter/subscription/confirmimportform.html",
            {'form': form, 'subscribers': addresses},
        )

    """ URLs """
    def get_urls(self):
        urls = super(SubscriptionAdmin, self).get_urls()

        my_urls = [
            url(r'^import/$',
                self._wrap(self.subscribers_import),
                name=self._view_name('import')),
            url(r'^import/confirm/$',
                self._wrap(self.subscribers_import_confirm),
                name=self._view_name('import_confirm')),

            # Translated JS strings - these should be app-wide but are
            # only used in this part of the admin. For now, leave them here.
            url(r'^jsi18n/$',
                javascript_catalog,
                {'packages': ('newsletter',)},
                name='newsletter_js18n')
        ]

        return my_urls + urls


class ArticleImageInline(TabularDynamicInlineAdmin):
    model = ArticleImageItem
    extra = 0
    raw_id_fields = ('image',)


class ExcludeMealplanListFilter(admin.SimpleListFilter):
    # Human-readable title which will be displayed in the
    # right admin sidebar just above the filter options.
    title = _('Nachricht')

    # Parameter for the filter that will be used in the URL query.
    parameter_name = 'message__id'

    def lookups(self, request, model_admin):
        """
        Returns a list of tuples. The first element in each
        tuple is the coded value for the option that will
        appear in the URL query. The second element is the
        human-readable name for the option that will appear
        in the right sidebar.
        """
        return [(str(post.id), post.title + ' - ' + post.newsletter.title[0:23] + '...')
                for post in Message.objects.exclude(newsletter__title__icontains='speiseplan')]

    def queryset(self, request, queryset):
        """
        Returns the filtered queryset based on the value
        provided in the query string and retrievable via
        `self.value()`.
        """
        if self.value():
            return queryset.filter(post__id=int(self.value()))


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    fields = ('title', 'text', 'section_heading', 'get_message_link')
    readonly_fields = ('get_message_link',)
    inlines = (ArticleImageInline,)
    list_filter = (ExcludeMealplanListFilter,)
    search_fields = ('title',)

    change_list_template = 'admin/newsletter/article/change_list.html'

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.exclude(post__newsletter__title__icontains='speiseplan')

    if newsletter_settings.RICHTEXT_WIDGET:
        formfield_overrides = {
            models.TextField: {'widget': newsletter_settings.RICHTEXT_WIDGET},
        }

    def get_message_link(self, obj=None):
        obj = obj.post
        if obj.pk:  # if object has already been saved and has a primary key, show link to it
            url = reverse('admin:%s_%s_change' % (obj._meta.app_label, obj._meta.model_name), args=[force_text(obj.pk)])
            return """<a href="{url}">{text}</a>""".format(
                url=url,
                text=_("Edit %s") % obj.title,
            )
        return _("(save and continue editing to create a link)")
    get_message_link.short_description = _("Nachricht")
    get_message_link.allow_tags = True


admin.site.register(Newsletter, NewsletterAdmin)
admin.site.register(Submission, SubmissionAdmin)
admin.site.register(Message, MessageAdmin)
admin.site.register(Subscription, SubscriptionAdmin)
