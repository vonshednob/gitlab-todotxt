import setuptools
import pathlib

try:
    import docutils.core
    from docutils.writers import manpage
except ImportError:
    docutils = None
    manpage = None

from gitlab_todotxt import version


with open('README.md', encoding='utf-8') as fd:
    long_description = fd.read()


with open('LICENSE', encoding='utf-8') as fd:
    licensetext = fd.read()


def compile_documentation():
    htmlfiles = []

    if docutils is None:
        return htmlfiles

    src = pathlib.Path('./doc')

    dst = pathlib.Path('./gitlab_todotxt/doc')
    dst.mkdir(exist_ok=True)
    
    pathlib.Path('./man').mkdir(exist_ok=True)

    man_pter = None

    if None not in [docutils, manpage] and src.exists():
        for fn in src.iterdir():
            if fn.suffix == '.rst':
                if fn.stem == 'pter':
                    man_pter = str(fn)
                dstfn = str(dst / (fn.stem + '.html'))
                docutils.core.publish_file(source_path=str(fn),
                                           destination_path=dstfn,
                                           writer_name='html')
                htmlfiles.append('docs/' + fn.stem + '.html')

    if man_pter is not None:
        docutils.core.publish_file(source_path=man_pter,
                                   destination_path='man/gitlab-todotxt.1',
                                   writer_name='manpage')

    return htmlfiles


setuptools.setup(
    name='gitlab-todotxt',
    version=version.__version__,
    description="Synchronise your GitLab issues to a todo.txt file",
    long_description=long_description,
    long_description_content_type='text/markdown',
    url="https://github.com/vonshednob/gitlab-todotxt",
    author="R",
    author_email="devel+gitlab-todotxt@kakaomilchkuh.de",
    entry_points={'console_scripts': ['gitlab-todotxt = gitlab_todotxt.main:run']},
    packages=['gitlab_todotxt'],
    package_data={'gitlab_todotxt': compile_documentation()},
    install_requires=[],
    extras_require={'xdg': ['pyxdg']},
    python_requires='>=3.0',
    classifiers=['Development Status :: 4 - Beta',
                 'License :: OSI Approved :: MIT License',
                 'Natural Language :: English',
                 'Programming Language :: Python :: 3',])

