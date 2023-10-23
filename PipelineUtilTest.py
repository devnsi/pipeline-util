import os
import unittest
from argparse import Namespace

import PipelineUtil


class Test(unittest.TestCase):

    file = PipelineUtil.ExternalConfig.config_file

    def setUp(self):
        if os.path.exists(self.file):
            os.remove(self.file)

    def test_add(self):
        PipelineUtil.run_command(Namespace(which='add', alias='testgitlab', url='https://testgitlab.com', token=''))

    def test_add_update(self):
        self.writeOne()
        PipelineUtil.run_command(Namespace(which='add', alias='testgitlab', url='https://testgitlab.com', token=''))

    def test_list(self):
        self.writeOne()
        PipelineUtil.run_command(Namespace(which='list'))

    def test_list_empty(self):
        PipelineUtil.run_command(Namespace(which='list'))

    def test_remove(self):
        self.writeOne()
        PipelineUtil.run_command(Namespace(which='remove', alias='testgitlab'))

    def test_remove_empty(self):
        PipelineUtil.run_command(Namespace(which='remove', alias='testgitlab'))

    def test_switch(self):
        self.writeOne()
        PipelineUtil.run_command(Namespace(which='switch', alias='testgitlab'))

    def test_run(self):
        PipelineUtil.run_command(Namespace(which='run', projects='testproject', references='develop',
                                           limit_projects=1, limit_pipelines=1, limit_pipelines_search_depth=1,
                                           verbose=True))

    def write(self, content):
        with open(self.file, 'w') as f:
            f.write(content)

    def writeOne(self):
        self.write("""
[servers.testgitlab]
url = "https://testgitlab.com"
active = true
""")


if __name__ == '__main__':
    unittest.main()
