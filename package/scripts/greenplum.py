from __future__ import with_statement
import sys
import urllib
import os
from os import path
from textwrap import dedent
from resource_management import *
import greenplum_installer
import utilities
import greenplum_webcc_installer


def preinstallation_configure(env):
    """Should be run before installation on all hosts."""

    import params

    env.set_params(params)

    # Create user
    Group(
        params.admin_group
    )

    User(
        params.admin_user,
        groups=[params.admin_group],
        action="create", shell="/bin/bash"
    )
    Execute(format("echo '{params.admin_user_pwd}' | passwd --stdin {params.admin_user}"), user="root")

    configure_ssh_keys(params.admin_user)

    Execute("cat /dev/null > ~/.ssh/known_hosts", user=params.admin_user)
    for host in params.all_nodes:
        Execute("ssh-keyscan {0} >> ~/.ssh/known_hosts".format(host), user=params.admin_user)
        Logger.info("ssh-keyscan {0} >> ~/.ssh/known_hosts".format(host))

    if params.set_kernel_parameters:
        utilities.set_kernel_parameters(utilities.get_configuration_file('system-variables'))

        TemplateConfig(
            params.security_conf_file,
            template_tag="limits",
            owner=params.admin_user, mode=0644
        )


def greenplum_package_install(env):
    """Perform install for master and segment"""

    import params

    if path.exists(params.absolute_installation_path):
        return
    with greenplum_installer.GreenplumDistributed.from_source(params.installer_location,
                                                              params.tmp_dir) as distributed_archive:
        with distributed_archive.get_installer() as gp_install_script:
            version_installation_path = path.join(params.installation_path,
                                                  'greenplum-db-%s' % gp_install_script.get_version())
            Directory(
                version_installation_path,
                action="create",
                owner=params.admin_user, group=params.admin_group, mode=0755
            )
            gp_install_script.install_to(version_installation_path)

    relative_greenplum_path_file = path.join(version_installation_path, 'greenplum_path.sh')
    Execute("sed -i 's@^GPHOME=.*@GPHOME={0}@' '{1}';".format(version_installation_path, relative_greenplum_path_file))
    source_env = os.environ.copy().update(utilities.get_environment(params.source_cmd))
    Link(params.absolute_installation_path, to=version_installation_path)
    Execute(format("chown -R {params.admin_user}.{params.admin_group} /usr/local/greenplum*"), user="root")


def master_install(env):
    """Perform installation for master node."""

    import params
    greenplum_package_install(env)

    create_host_files()

    tmp_scp = "/tmp/scp.exp"
    greenplum_webcc_installer.create_scp(tmp_scp)

    for host in params.all_nodes:
        try:
            Execute(format(
                "expect {tmp_scp} {host} {params.admin_user} {params.admin_user_pwd} ~/.ssh/id_rsa.pub ~/.ssh/authorized_keys"),
                    user=params.admin_user)
        except Fail as exception:
            pass

    try:
        gpinitsystem_command = ['gpinitsystem', '-a', '-c "%s"' % params.greenplum_initsystem_config_file]

        if params.master_standby_node != None:
            gpinitsystem_command.append('-s "' + params.master_standby_node + '"')

        if params.mirroring_enabled and params.enable_mirror_spreading:
            gpinitsystem_command.append('-S')

        Execute(
            params.source_cmd + "gpssh-exkeys -f /usr/local/greenplum-db/greenplum_hosts",
            user=params.admin_user
        )
        Execute(
            params.source_cmd + " ".join(gpinitsystem_command),
            user=params.admin_user
        )
    except Fail as exception:
        Logger.info("gpinitsystem reported failure to install.  Scanning logs manually for consensus.")
        import time
        time.sleep(1)
        logfile = re.search(format(r'.*:-(/home/[^/]+/gpAdminLogs/gpinitsystem_[0-9]+\.log)'), str(exception))
        if logfile == None:
            Logger.error("No log file could be found to be scanned.  Failing.")
            # raise exception
            return

        logfile = logfile.group(1)
        Logger.info("Scanning log file: %s" % logfile)

        log_file_errors = scan_installation_logs(logfile, "warn")
        if len(log_file_errors) > 0:
            Logger.error("Errors detected in logfile:")

            for error in log_file_errors:
                Logger.error(" - %s" % error)

            Logger.error("Due to above errors Greenplum installation marked failed.")

            # raise exception
            return
        else:
            Logger.info("No consensus.  Installation considered successful.")
            Logger.warning(
                ">>>>> The log file located at %s should be reviewed so any reported warnings can be fixed!" % logfile)


def configure_ssh_keys(user):
    """Configure  ssh-keys"""
    import params
    ssh_dir = format('/home/{user}/.ssh')
    idrsa_file = path.join(ssh_dir, 'id_rsa')
    idrsapub_file = path.join(ssh_dir, 'id_rsa.pub')
    authkeys_file = path.join(ssh_dir, 'authorized_keys')

    # Generate an rsa id if the user doesn't already have one
    Execute(
        'cat /dev/zero | ssh-keygen -q -t rsa -b 2048 -N ""',
        not_if=format('test -f {idrsa_file}'),
        user=user
    )

    # if not path.exists(authkeys_file):
    #     Execute(
    #         format('cat {idrsapub_file} > {authkeys_file}'),
    #         user = user
    #     )


def configure_and_distribute_ssh_keys(user, hostfile):
    """Configure passwordless login for user on all machines."""
    import params

    ssh_dir = format('/home/{user}/.ssh')
    idrsa_file = path.join(ssh_dir, 'id_rsa')
    idrsapub_file = path.join(ssh_dir, 'id_rsa.pub')
    authkeys_file = path.join(ssh_dir, 'authorized_keys')

    # Generate an rsa id if the user doesn't already have one
    Execute(
        'cat /dev/zero | ssh-keygen -q -t rsa -b 2048 -N ""',
        not_if=format('test -f {idrsa_file}'),
        user=user
    )

    # Prepare to distribute key
    # '|| exit 0' because we don't care if directory already exists
    Execute(
        params.source_cmd +
        utilities.gpsshify('mkdir ' + ssh_dir + ' || exit 0', hostfile=hostfile),
        user="root"
    )

    # Distribute public key
    Execute(
        format(params.source_cmd + "gpscp -f {hostfile} {idrsapub_file} =:{idrsapub_file};")
    )

    # Trust public key
    Execute(
        params.source_cmd + utilities.gpsshify(format("""
            cat '{idrsapub_file}' >> {authkeys_file};

            chown -R '{user}' '{ssh_dir}';
            chmod -R 600 '{ssh_dir}';
            chmod 700 '{ssh_dir}';
        """), hostfile=hostfile),
        user="root"
    )

    # Distribute private key using public key
    Execute(
        format(params.source_cmd + "gpscp -f {hostfile} {idrsa_file} =:{idrsa_file};"),
        user=user
    )

    # Trust all hosts for all hosts for user
    trust_all_hosts_cmds = []
    for host in params.all_nodes:
        trust_all_hosts_cmds.append(format('ssh-keyscan {host} >> ~/.ssh/known_hosts;'))

    Execute(
        params.source_cmd +
        utilities.gpsshify(" ".join(trust_all_hosts_cmds), hostfile=hostfile),
        user=user
    )


def refresh_pg_hba_file():
    import params
    utilities.add_block_to_file(params.pg_hba_file, InlineTemplate(params.pg_hba_appendable_data).get_content(),
                                'zdata-gp')


def create_host_files():
    """Create segment and all host files in greenplum absolute installation path."""

    import params

    # Create segment hosts file
    TemplateConfig(
        params.greenplum_segment_hosts_file,
        owner=params.admin_user, mode=0644
    )

    # Create all hosts file
    TemplateConfig(
        params.greenplum_all_hosts_file,
        owner=params.admin_user, mode=0644
    )


def create_master_data_directory():
    """Create the master data directory, append relevant environment variable to admin user."""

    import params

    Directory(
        params.master_data_directory,
        action="create",
        create_parents=True,
        recursive_ownership=True,
        owner=params.admin_user,
        group=params.admin_group
    )

    utilities.append_bash_profile(params.admin_user,
                                  'export MASTER_DATA_DIRECTORY="%s";' % params.master_data_segment_directory)


def create_gpinitsystem_config(user, destination):
    """Create gpinitsystem_config file."""
    import params

    Directory(
        path.dirname(destination),
        action="create",
        create_parents=True,
        recursive_ownership=True,
        owner=user
    )

    TemplateConfig(
        destination,
        owner=user, mode=0644
    )


def add_psql_variables(user=None):
    import params

    if user == None:
        user = params.admin_user

    utilities.append_bash_profile(user,
                                  "source %s;" % path.join(params.absolute_installation_path, 'greenplum_path.sh'))
    utilities.append_bash_profile(user, 'export PGPORT="%s";' % params.master_port)
    utilities.append_bash_profile(user, 'export PGDATABASE="%s";' % params.database_name)


def is_running(pid_file):
    return utilities.is_process_running(pid_file, lambda filehandle: int(filehandle.readlines()[0]))


def scan_installation_logs(logFile, minimum_error_level='info'):
    """Given a log file, return if there are any log lines with an error level above minimum_error_level."""

    log_levels = {'debug': 1, 'info': 2, 'warn': 3, 'error': 4, 'fatal': 5}

    if minimum_error_level.lower() not in log_levels:
        raise ValueError('Invalid minimum_error_level value "%s".' % minimum_error_level.lower())

    error_lines = []
    minimum_error_level = log_levels[minimum_error_level.lower()]

    with open(logFile, 'r') as filehandle:
        for line in filehandle.readlines():
            matches = re.findall(r"\[([A-Z]+)\]", line)
            if len(matches) == 0:
                continue

            line_log_level = matches[0].lower()

            if line_log_level not in log_levels or log_levels[line_log_level] > minimum_error_level:
                error_lines.append(line)

    # Don't care about lines between sets of asterisks, are metadata and therefore don't need to be included.
    error_lines = remove_lines_between_delimiter(error_lines)

    return error_lines


def remove_lines_between_delimiter(lines, delimiter=r".*:-\*+$"):
    """Given a list of lines, remove all lines in between lines which match the given delimiter pattern, including the delimiter lines."""

    inside_delimiter = False
    lines_outside_delimiter = []

    for line in lines:
        line_is_delimiter = re.match(delimiter, line) != None

        if line_is_delimiter:
            inside_delimiter = not inside_delimiter

        if not inside_delimiter and not line_is_delimiter:
            lines_outside_delimiter.append(line)

    return lines_outside_delimiter
