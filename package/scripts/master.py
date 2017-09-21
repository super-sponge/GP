import sys
import os
import urllib
import greenplum
import utilities
import greenplum_webcc_installer
from resource_management import *

class Master(Script):

    def install(self, env):
        import params
        import time;

        if not params.license_accepted:
            sys.exit("Installation failed, license agreement not accepted.")

        if os.path.exists(params.master_data_segment_directory):
            Logger.info("Found master data directory.  Assuming Greenplum already installed.")
            return
        env.set_params(params)
        self.install_packages(env)

        time.sleep(200);
        greenplum.preinstallation_configure(env)
        greenplum.create_master_data_directory()
        greenplum.create_gpinitsystem_config(params.admin_user, params.greenplum_initsystem_config_file)
        greenplum.add_psql_variables()

        greenplum.master_install(env)

        ## gpmon requires gpdb to be in a running state when installing

        try:
            Execute(params.source_cmd + format(" gpperfmon_install  --enable --password {params.gpmon_password}  --port {params.master_port}"), user = params.admin_user);
            Execute(params.source_cmd + "gpstop -u",user=params.admin_user)
        except Fail as exception:
            Logger.error("Due to above errors Greenplum gpmon marked failed.")
            raise exception

        webcc_zippath = "/tmp/greenplum-cc-web.zip"
        # Attempt to locate locallay
        if not os.path.exists(webcc_zippath):
            # Attempt to download URL
            try:
                Logger.info('Downloading Greenplum from %s to %s.' % (params.webcc_installer_location, webcc_zippath))
                urllib.urlretrieve(params.webcc_installer_location, webcc_zippath)
            except IOError:
                pass
        webcc_installer = greenplum_webcc_installer.GreenplumWebCCInstaller(webcc_zippath)
        webcc_installer.unzip_web_package()

        Execute("expect " + webcc_installer.install_webcc_cmd(), user = "root");
        Execute(format("chown -R {params.admin_user}.{params.admin_group} /usr/local/greenplum*"), user = "root");

        webcc_setup = webcc_installer.setup_webcc_cmd(params.webcc_port)
        Execute(format("chmod 744 {webcc_setup}"), user = "root")
        Execute(params.source_cc_cmd + " ; expect " + webcc_setup, user = params.admin_user);
        Execute(params.source_cc_cmd + " ; gpcmdr --start sefon", user = params.admin_user);

        # Ambari requires service to be in a stopped state after installation
        try:
            self.status(env)
            self.stop(env)
        except ComponentIsNotRunning:
            pass

    def start(self, env):
        import params
        env.set_params(params)

        self.configure(env)

        Execute(
            params.source_cmd + "gpstart -a -v",
            user=params.admin_user
        )
        Execute(
            params.source_cc_cmd + " ; gpcmdr --start sefon",
            user = params.admin_user
        )

    def stop(self, env):
        import params

        if not greenplum.is_running(params.master_pid_path):
            print "Greenplum is not running."
            return

        Execute(
            params.source_cmd + "gpstop -a -M smart -v",
            user=params.admin_user
        )
        Execute(
            params.source_cc_cmd + " ; gpcmdr --stop sefon",
            user = params.admin_user
        )

    def forcestop(self, env):
        import params

        Execute(
            params.source_cmd + "gpstop -a -M fast -v",
            user=params.admin_user
        )

    def recover_master(self):
        print "Noop: Recovering master"

    def configure(self, env):
        import params

        greenplum.create_host_files()
        greenplum.preinstallation_configure(env)
        greenplum.refresh_pg_hba_file()

    def status(self, env):
        import params
        if not greenplum.is_running(params.master_pid_path):
            raise ComponentIsNotRunning()

if __name__ == "__main__":
    Master().execute()
