import sys
import os
import greenplum
import utilities
from resource_management import *

class StandbyMaster(Script):

    def install(self, env):
        import params

        if not params.license_accepted:
            sys.exit("Installation failed, license agreement not accepted.")

        env.set_params(params)

        greenplum.preinstallation_configure(env)
        greenplum.create_master_data_directory()
        greenplum.greenplum_package_install(env)
        greenplum.add_psql_variables()

        self.install_packages(env)

    def start(self, env):
        print 'Cannot start only standby master.'
        return

    def stop(self, env):
        import params
        import time
        while greenplum.is_running(params.master_pid_path):
            sys.stdout.write('.')
            time.sleep(1)

    def configure(self, env):
        greenplum.create_host_files()
        greenplum.preinstallation_configure(env)
         
    def status(self, env):
        import params
        if not greenplum.is_running(params.master_pid_path):
            raise ComponentIsNotRunning()

if __name__ == "__main__":
    StandbyMaster().execute()