import os
import plac
import za
import za.util
import za.test.data

logger = za.get_logger(__name__)


@plac.annotations(
    name=("name of data source", "positional"),
    url=("database URL", "option"),
    echo=("echo SQL?", "flag"),
    wipe=("wipe beforehand?", "flag"),
    must_be_clean=("check for an empty database?", "flag"))
def main(
        name,
        url=os.environ.get("ZA_TEST_DATABASE_URL"),
        echo=False,
        wipe=False,
        must_be_clean=False):
    """Populate a database with synthetic data."""

    za.configure_globals()

    za.test.data.fill(
        name,
        url=url,
        echo=echo,
        wipe=wipe,
        must_be_clean=must_be_clean)

script_main = za.util.script_main(main, __name__)
