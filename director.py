import yaml
import paramiko
import os
import threading
from jinja2 import Template
from contextlib import contextmanager
from colorama import Fore
import subprocess

def red(message):
    return Fore.RED + message + Fore.RESET


def green(message):
    return Fore.GREEN + message + Fore.RESET


def yellow(message):
    return Fore.YELLOW + message + Fore.RESET


class RemoteCommandException(Exception):
    '''command process return code != 0'''

class CommandException(Exception):
    '''command process return code != 0'''

class RemoteCommandThread(threading.Thread):
    def __init__(self, method, client, command):
        threading.Thread.__init__(self)
        self.method = method
        self.client = client
        self.command = command
        self.result = None


    def run(self):
        self.result = self.method(self.client, self.command)


class Director:
    config = None
    clients = None
    pool = None

    def __init__(self, configuration_file):
        config = { 'hosts': [], 'parallel': False, 'warn_only': False }
        f = open(configuration_file, 'r')
        self.config = dict_merge(config, yaml.safe_load(f))
        f.close()
        self.clients = []


    def connect(self):
        ssh_config = paramiko.SSHConfig()
        user_config_file = os.path.expanduser('~/.ssh/config')

        if os.path.exists(user_config_file):
            with open(user_config_file) as f:
                ssh_config.parse(f)

        for host in self.config['hosts']:
            client = paramiko.SSHClient()
            client._policy = paramiko.WarningPolicy()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            user_config = ssh_config.lookup(host)
            cfg = {'hostname': user_config['hostname'], 'username': user_config['user'], 'key_filename': user_config['identityfile'][0]}
            client.connect(**cfg)
            client.hostname = host
            print(host + ': connected')
            self.clients.append(client)


    def remote_command_as(self, command, user, wd='.', stdout_only = True):
        return self.remote_command('sudo su - ' + user + ' -c \'cd ' + wd + ' && ' + command + '\'', stdout_only)


    def remote_command(self, command, stdout_only = True):
        threads = []
        results = []

        for client in self.clients:
            if(self.config['parallel'] == True):
                t = RemoteCommandThread(self.client_remote_command, client, command)
                threads.append(t)
                t.start()
            else:
                r = self.client_remote_command(client, command)

                if type(r) is RemoteCommandException:
                    raise RemoteCommandException

                if(stdout_only == True):
                    results.append(r[1].read())
                else:
                    results.append(r)
        
        for t in threads:
            t.join()

        for t in threads:
            if type(t.result) is RemoteCommandException:
                raise RemoteCommandException
            
            if(stdout_only == True):    
                results.append(t.result[1].read())
            else:
                results.append(t.result)

        return results
    

    def client_remote_command(self, client, command):
        print(client.hostname + ': Executing ' + command)
        result = client.exec_command(command)

        if(result[1].channel.recv_exit_status() != 0):
            if(self.config['warn_only'] == True):
                message = result[2].read()
                if message != '':
                    print(yellow(message))
            else:
                result = RemoteCommandException('Remote command error: ' + result[2].read())

        return result

    
    def download(self, source, destination):
        for c in self.clients:
            print(c.hostname + ': Downloading ' + destination + ' < ' + source)
            sftp_client = c.open_sftp()
            sftp_client.get(source, destination)
            sftp_client.close()

    
    def upload(self, source, destination):
        for c in self.clients:
            print(c.hostname + ': Uploading ' + source + ' > ' + destination)
            sftp_client = c.open_sftp()
            sftp_client.put(source, destination)
            sftp_client.close()


    def upload_template(self, source, destination, params):
        with open(source) as f:
            t = Template(f.read())
            data = t.render(params)
            
        for c in self.clients:
            print(c.hostname + ': Uploading ' + source + ' > ' + destination)
            sftp_client = c.open_sftp()
            sftp_client.open(destination, "w").write(data)
            sftp_client.close()
    

    def local_command(self, command):
        print('Local > ' + command)
        popen = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE)
        result = popen.communicate()

        if popen.returncode == 1:
            raise CommandException

        return result[0]

    
    def remote_dir_exists(self, dir):
        try:
            self.remote_command('[[ -d ' + dir + ' ]]', stdout_only = False)
        except RemoteCommandException as e:
            return False

        return True
    
    
    def remote_file_exists(self, file):
        try:
            self.remote_command('[[ -f ' + file + ' ]]', stdout_only = False)
        except RemoteCommandException as e:
            return False
        
        return True
        
    
    def rm(self, p, recursive=True):
        if recursive:
            self.remote_command('rm -rf ' + p)
        else:
            self.remote_command('rm ' + p)

    @contextmanager
    def settings(self, **kwargs):
        original_config = self.config
        original_clients = self.clients
        self.config = dict(original_config)

        for name, value in kwargs.items():
            if name == 'clients':
                self.clients = value
                continue

            self.config[name] = value

        yield self.config
        self.config = original_config
        self.clients = original_clients


def dict_merge(x, y):
    z = x.copy()
    z.update(y)
    return z
