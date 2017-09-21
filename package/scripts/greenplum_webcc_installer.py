from __future__ import with_statement
import os, re
import tempfile
import shutil
import zipfile


def create_webcc_expect(expect_path, webcc_bin):
    expectScript = """#!/usr/bin/expect
set timeout -1
spawn bash %s
send "q" 
expect "****************************\\n" {send "yes\\n"}
expect "****************************\\n" {send "\\n"}
expect "****************************\\n" {send "yes\\n"}
expect "****************************\\n" {send "yes\\n"}
expect eof
""" % webcc_bin

    print ("create " + expect_path)
    with open(expect_path, 'w') as f:
        f.write(expectScript)


def create_webcc_setup(expect_path, webcc_port):
    expectScript = """#!/usr/bin/expect
set timeout -1
spawn gpcmdr --setup
expect "Please enter the instance name" {send "sefon\\n"}
expect "(Press ENTER to use instance name)" {send "\\n"}
expect "Greenplum Database remote? Yy/Nn (default=N)" {send "\\n"}
expect "Greenplum Database use? (default=5432)" {send "\\n"}
expect "Enable kerberos login for this instance? Yy/Nn (default=N)" {send "\\n"}
expect ")" {send "%s\\n"}
expect "(default=N)" {send "\\n"}
expect "Copy the instance to a standby master host Yy/Nn (default=Y)" {send "n\\n"}
expect eof""" % (webcc_port)
    print ("create " + expect_path)
    with open(expect_path, 'w') as f:
        f.write(expectScript)


def create_scp(expect_path):
    expectScript = """#!/usr/bin/expect
set timeout 10

if {$argc < 5} {
    #do something
    send_user "usage: $argv0 <remote_host> <remote_user> <remote_pwd> <local_file> <dest_file>"
    exit
}

set host [lindex $argv 0]
set username [lindex $argv 1]
set password [lindex $argv 2]
set src_file [lindex $argv 3]
set dest_file [lindex $argv 4]
spawn scp $src_file $username@$host:$dest_file
 expect {
 "(yes/no)?"
   {
    send "yes\\n"
    expect "*assword:" { send "$password\n"}
 }
 "*password: "
{
 send "$password\\n"
}
}
expect "100%"
expect eof"""
    print ("create " + expect_path)
    with open(expect_path, 'w') as f:
        f.write(expectScript)


def unzip_webcc_package(zip_path, bin_path):
    if zipfile.is_zipfile(zip_path):
        zipf = zipfile.ZipFile(zip_path)
        file_name = zipf.namelist()[0]
        if not os.path.exists(os.path.join(bin_path, file_name)):
            print ("unzip " + zip_path)
            zipf.extractall(bin_path)
        return os.path.join(bin_path, file_name)


class GreenplumWebCCInstaller(object):
    @staticmethod
    def make_tmpfile(tmp_dir=None, suffix=None):
        """Create a temporary named file and return its path."""
        filehandle, tmp_path = tempfile.mkstemp(dir=tmp_dir, suffix=suffix)
        os.close(filehandle)  # Don't need a filehandle
        return tmp_path

    def __init__(self, file_path, is_temporary=False):
        self.__file_path = file_path
        self.__delete_file_on_close = is_temporary
        self.__tmp_rpm_dir = tempfile.gettempdir()
        self.__webcc_install_cmd = GreenplumWebCCInstaller.make_tmpfile(suffix=".exp")
        self.__webcc_setup_cmd = GreenplumWebCCInstaller.make_tmpfile(suffix=".exp")
        self.__webbin_path = None

    def __del__(self):
        self.close()

    def unzip_web_package(self):
        if zipfile.is_zipfile(self.__file_path):
            zipf = zipfile.ZipFile(self.__file_path)
            file_name = zipf.namelist()[0]
            print ("unzip " + self.__file_path)
            webbin_path = os.path.join(self.__tmp_rpm_dir, file_name)
            if not os.path.exists(webbin_path):
                zipf.extractall(self.__tmp_rpm_dir)
            return webbin_path

    def webbin_path(self):
        if self.__webbin_path is None:
            return self.unzip_web_package()
        else:
            return self.__webbin_path

    def install_webcc_cmd(self):
        create_webcc_expect(self.__webcc_install_cmd, self.webbin_path())
        return "expect " + self.__webcc_install_cmd

    def setup_webcc_cmd(self, port="28080"):
        create_webcc_setup(self.__webcc_setup_cmd, port)
        return "expect " + self.__webcc_setup_cmd

    def close(self):
        if self.__delete_file_on_close:
            print "clean temp files"
            if os.path.exists(self.__tmp_rpm_dir):
                shutil.rmtree(self.__tmp_rpm_dir)
            if os.path.exists(self.__webcc_install_cmd):
                os.remove(self.__webcc_install_cmd)
            if os.path.exists(self.__webcc_setup_cmd):
                os.remove(self.__webcc_setup_cmd)


if __name__ == "__main__":
    bin_file = unzip_webcc_package("/root/greenplum-cc-web-3.3.0-LINUX-x86_64.zip", "/tmp")
    create_scp("/tmp/scp.exp")
    cc_installer = GreenplumWebCCInstaller("/tmp/greenplum-cc-web-3.3.0-LINUX-x86_64.zip", True)
    bin_file = cc_installer.unzip_web_package()
    print(bin_file)
    print(cc_installer.install_webcc_cmd())
    print(cc_installer.setup_webcc_cmd("28081"))
