"""TO-DO: Write a description of what this XBlock is."""

import json
import hashlib
import os
import logging
import pkg_resources
import shutil

from functools import partial
from django.conf import settings
from django.core.files import File
from django.core.files.storage import default_storage
from django.template import Context, Template
from django.utils import timezone
from webob import Response
## from openedx.core.djangoapps.site_configuration import helpers as configuration_helpers

from xblock.core import XBlock
from xblock.fields import Integer, Scope, String, Dict, DateTime
from xblock.fragment import Fragment

# Make '_' a no-op so we can scrape strings
_ = lambda text: text

log = logging.getLogger(__name__)

HTMLPACKAGE_ROOT = os.path.join(settings.MEDIA_ROOT, 'htmlpackage')
HTMLPACKAGE_URL = os.path.join(settings.MEDIA_URL, 'htmlpackage')

class HtmlPackageXBlock(XBlock):
    """
    TO-DO: document what your XBlock does.
    """

    # Fields are defined on the class.  You can access them in your code as
    # self.<fieldname>.

    display_name = String(
        display_name=_("Display Name"),
        help=_("Display name for this module"),
        default="HTML package",
        scope=Scope.settings,
    )
    zip_file = String(
        display_name=_("Upload zip file"),
        scope=Scope.settings,
    )
    path_index_page = String(
        display_name=_("Path to the index page in zip file"),
        scope=Scope.settings,
    )
    zip_file_meta = Dict(
        scope=Scope.content
    )
    icon_class = String(
        default="video",
        scope=Scope.settings,
    )
    width = Integer(
        display_name=_("Display Width (px)"),
        help=_('Width of iframe, if empty, the default 100%'),
        scope=Scope.settings
    )
    height = Integer(
        display_name=_("Display Height (px)"),
        help=_('Height of iframe'),
        default=450,
        scope=Scope.settings
    )

    has_author_view = True

    def resource_string(self, path):
        """Handy helper for getting resources from our kit."""
        data = pkg_resources.resource_string(__name__, path)
        return data.decode("utf8")

    # TO-DO: change this view to display your data your own way.
    def student_view(self, context=None):
        """
        The primary view of the HtmlPackageXBlock, shown to students
        when viewing courses.
        """
        context_html = self.get_context_student()
        template = self.render_template('static/html/htmlpackage.html', context_html)
        frag = Fragment(template)
        frag.add_css(self.resource_string("static/css/htmlpackage.css"))
        frag.add_javascript(self.resource_string("static/js/src/htmlpackage.js"))
        frag.initialize_js('HtmlPackageXBlock')
        return frag

    def studio_view(self, context=None):
        context_html = self.get_context_studio()
        template = self.render_template('static/html/studio.html', context_html)
        frag = Fragment(template)
        frag.add_css(self.resource_string("static/css/htmlpackage.css"))
        frag.add_javascript(self.resource_string("static/js/src/studio.js"))
        frag.initialize_js('HtmlPackageXBlock')
        return frag

    def author_view(self, context=None):
        html = self.render_template("static/html/author_view.html", context)
        frag = Fragment(html)
        return frag

    @XBlock.handler
    def studio_submit(self, request, suffix=''):
        self.display_name = request.params['display_name']
        self.width = request.params['width']
        self.height = request.params['height']
        self.icon_class = 'video'

        if hasattr(request.params['file'], 'file'):
            zip_file = request.params['file'].file

            # First, save scorm file in the storage for mobile clients
            self.zip_file_meta['sha1'] = self.get_sha1(zip_file)
            self.zip_file_meta['name'] = zip_file.name
            self.zip_file_meta['path'] = path = self._file_storage_path()
            self.zip_file_meta['last_updated'] = timezone.now().strftime(DateTime.DATETIME_FORMAT)

            if default_storage.exists(path):
                log.info('Removing previously uploaded "{}"'.format(path))
                default_storage.delete(path)

            default_storage.save(path, File(zip_file))
            self.zip_file_meta['size'] = default_storage.size(path)
            log.info('"{}" file stored at "{}"'.format(zip_file, path))

            # Check whether HTMLPACKAGE_ROOT exists
            if not os.path.exists(HTMLPACKAGE_ROOT):
                os.mkdir(HTMLPACKAGE_ROOT)

            # Now unpack it into HTMLPACKAGE_ROOT to serve to students later
            path_to_file = os.path.join(HTMLPACKAGE_ROOT, self.location.block_id)

            if os.path.exists(path_to_file):
                shutil.rmtree(path_to_file)

            if hasattr(zip_file, 'temporary_file_path'):
                os.system('unzip {} -d {}'.format(zip_file.temporary_file_path(), path_to_file))
            else:
                temporary_path = os.path.join(HTMLPACKAGE_ROOT, zip_file.name)
                temporary_zip = open(temporary_path, 'wb')
                zip_file.open()
                temporary_zip.write(zip_file.read())
                temporary_zip.close()
                os.system('unzip {} -d {}'.format(temporary_path, path_to_file))
                os.remove(temporary_path)

            self.set_fields_xblock(path_to_file)

        return Response(json.dumps({'result': 'success'}), content_type='application/json')

    def get_context_studio(self):
        return {
            'field_display_name': self.fields['display_name'],
            'field_zip_file': self.fields['zip_file'],
            'field_width': self.fields['width'],
            'field_height': self.fields['height'],
            'htmlpackage_xblock': self
        }

    def get_context_student(self):
        zip_file_path = ''
        if self.zip_file:
            scheme = 'https' if settings.HTTPS == 'on' else 'http'
            zip_file_path = '{}://{}{}'.format(
                scheme,
                configuration_helpers.get_value('site_domain', settings.ENV_TOKENS.get('LMS_BASE')),
                # settings.ENV_TOKENS.get('LMS_BASE'),
                self.zip_file
            )

        return {
            'zip_file_path': zip_file_path,
            'htmlpackage_xblock': self
        }

    def render_template(self, template_path, context):
        template_str = self.resource_string(template_path)
        template = Template(template_str)
        return template.render(Context(context))

    def set_fields_xblock(self, path_to_file):
        self.path_index_page = 'index.html'
        self.zip_file = os.path.join(HTMLPACKAGE_URL, '{}/{}'.format(self.location.block_id, self.path_index_page))

    def _file_storage_path(self):
        """
        Get file path of storage.
        """
        path = (
            '{loc.org}/{loc.course}/{loc.block_type}/{loc.block_id}'
            '/{sha1}{ext}'.format(
                loc=self.location,
                sha1=self.zip_file_meta['sha1'],
                ext=os.path.splitext(self.zip_file_meta['name'])[1]
            )
        )
        return path

    def get_sha1(self, file_descriptor):
        """
        Get file hex digest (fingerprint).
        """
        block_size = 8 * 1024
        sha1 = hashlib.sha1()
        for block in iter(partial(file_descriptor.read, block_size), ''):
            sha1.update(block)
        file_descriptor.seek(0)
        return sha1.hexdigest()

    def student_view_data(self):
        """
        Inform REST api clients about original file location and it's "freshness".
        Make sure to include `student_view_data=htmlpackagexblock` to URL params in the request.
        """
        if self.zip_file and self.zip_file_meta:
            return {
                'last_modified': self.zip_file_meta.get('last_updated', ''),
                'scorm_data': default_storage.url(self._file_storage_path()),
                'size': self.zip_file_meta.get('size', 0),
                'index_page': self.path_index_page,
            }
        return {}

    # TO-DO: change this to create the scenarios you'd like to see in the
    # workbench while developing your XBlock.
    @staticmethod
    def workbench_scenarios():
        """A canned scenario for display in the workbench."""
        return [
            ("HtmlPackageXBlock",
             """<htmlpackage/>
             """),
            ("Multiple HtmlPackageXBlock",
             """<vertical_demo>
                <htmlpackage/>
                <htmlpackage/>
                <htmlpackage/>
                </vertical_demo>
             """),
        ]
