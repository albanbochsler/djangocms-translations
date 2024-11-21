from setuptools import find_packages, setup

from djangocms_translations import __version__


REQUIREMENTS = [
    'django-cms>=4.1',
    'django-appconf>=1.0,<2',
    'djangocms-versioning>=2.1.0',
    'djangocms-text-ckeditor>=5.1.2',
    'django-extended-choices',
    'pygments',
    'yurl',
    'requests',
    'six',
    'celery',  # aldryn-celery supports only 3.X
]


CLASSIFIERS = [
    'Development Status :: 5 - Production/Stable',
    'Environment :: Web Environment',
    'Intended Audience :: Developers',
    'License :: OSI Approved :: BSD License',
    'Operating System :: OS Independent',
    'Programming Language :: Python',
    'Programming Language :: Python :: 3',
    'Programming Language :: Python :: 3.11',
    'Framework :: Django',
    'Framework :: Django :: 4.2',
    'Framework :: Django CMS',
    'Framework :: Django CMS :: 4.1',
    'Topic :: Internet :: WWW/HTTP',
    'Topic :: Internet :: WWW/HTTP :: Dynamic Content',
    'Topic :: Software Development',
    'Topic :: Software Development :: Libraries',
]


setup(
    name='djangocms-translations',
    version=__version__,
    author='Divio AG',
    author_email='info@divio.ch',
    url='https://github.com/divio/djangocms-translations',
    license='BSD',
    description='Send django CMS content for translation to 3rd party providers.',
    long_description=open('README.rst').read(),
    packages=find_packages(exclude=['tests']),
    include_package_data=True,
    zip_safe=False,
    install_requires=REQUIREMENTS,
    classifiers=CLASSIFIERS,
    test_suite='tests.settings.run',
)
