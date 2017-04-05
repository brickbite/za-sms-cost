import setuptools
import setuptools.extension

with open("requirements.txt") as file_:
    install_requires = file_.readlines()

extras_require = {
    "doc": [
        "Sphinx==1.2.2",
        "sphinxcontrib-blockdiag==1.4.4",
        "sphinxcontrib-nwdiag==0.7.1",
        "sphinxcontrib-seqdiag==0.7.2"]}

console_scripts = [
    "za-psql = za.tools.psql:script_main",
    "za-dbfill = za.tools.dbfill:script_main",
    "za-rules-list = za.tools.rules_list:script_main",
    "za-rules-apply = za.tools.rules_apply:script_main",
    "za-tag-list = za.tools.tag_list:script_main",
    "za-tag-set = za.tools.tag_set:script_main",
    "za-serve-gunicorn = za.tools.serve_gunicorn:script_main"]

setuptools.setup(
    name="za",
    version="0.1.2",
    packages=setuptools.find_packages(),
    install_requires=install_requires,
    extras_require=extras_require,
    test_suite="nose.collector",
    include_package_data=True,
    entry_points={"console_scripts": console_scripts})
