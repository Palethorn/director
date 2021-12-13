import os
import sys
import yaml
import paramiko
import threading
import subprocess
from colorama import Fore
from jinja2 import Template
from contextlib import contextmanager

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
    verbose = 2

    DEBUG = 3
    INFO = 2
    WARN = 1
    ERROR = 0

    def __init__(self, configuration_file, verbose):
        self.verbose = verbose
        self.loadenv()

        if os.getenv('CONFIG_BASE_PATH'):
            configuration_file = os.getenv('CONFIG_BASE_PATH') + '/' + configuration_file

        if not os.path.exists(configuration_file):
            print(red('Unable to open configuration file: ' + configuration_file))
            sys.exit()

        config = { 'hosts': [], 'parallel': False, 'warn_only': False }
        f = open(configuration_file, 'r')
        self.config = dict_merge(config, yaml.safe_load(f))

        if os.getenv('SSH_USER'):
            self.config['ssh_user'] = os.getenv('SSH_USER')

        if os.getenv('USE_SUDO'):
            if 'yes' == os.getenv('USE_SUDO'):
                self.config['use_sudo'] = True
            else:
                self.config['use_sudo'] = False

        self.config['config_base_path'] = os.path.dirname(configuration_file)

        f.close()
        self.clients = []

    def loadenv(self, env_path=None):
        cwd = os.getcwd()
        f = None

        if None == env_path:
            env_path = cwd + '/.env'

        if not os.path.exists(env_path):
            self.log('Environment file %s does not exist' % env_path, self.WARN)
            return
        
        self.log('Loading environment from %s' % (env_path), self.DEBUG)
        f = open(env_path, 'r')

        line = f.readline()

        while line != '':
            [ key, val ] = line.strip().split('=')
            os.environ[key] = val
            line = f.readline()
        
        f.close()


    def abort(self, message):
        self.log(red(message), self.ERROR)
        sys.exit(1)


    def connect(self):
        self.log('Connecting to hosts', self.INFO)
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
            port = 22
            user = os.environ['USER']
            private_key = os.environ['HOME'] + '/.ssh/id_rsa'
            hostname = host
            
            if 'port' in user_config:
                port = user_config['port']

            if 'user' in user_config:
                user = user_config['user']

            if 'identityfile' in user_config:

                private_key = user_config['identityfile'][0]
            
            if 'hostname' in user_config:
                hostname = user_config['hostname']

            # Setting overrides if any
            if 'ssh_port' in self.config:
                port = self.config['ssh_port']

            if 'ssh_user' in self.config:
                user = self.config['ssh_user']
            
            if 'ssh_private_key' in self.config:
                private_key = self.config['ssh_private_key']

            cfg = {'hostname': hostname, 'username': user, 'key_filename': private_key, 'port': port}
            client.connect(**cfg)
            client.hostname = host
            self.log(host + ': connected', self.DEBUG)
            self.clients.append(client)
        
        self.log('Connected', self.INFO)


    def remote_command_as(self, command, user, wd='.', stdout_only = True):
        if self.config['use_sudo']:
            return self.remote_command('sudo su - %s -c \'cd %s && %s\'' % (user, wd, command), stdout_only)
        
        return self.remote_command('cd %s && %s' % (wd, command), stdout_only)



    def remote_command(self, command, stdout_only = True, print_error = True):
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
                    if(print_error == True):
                        self.log(str(r), self.ERROR)

                    raise RemoteCommandException

                if(stdout_only == True):
                    results.append(r[1].read())
                else:
                    results.append(r)

                self.log(r[1].read(), self.INFO)
        
        for t in threads:
            t.join()

        for t in threads:
            if type(t.result) is RemoteCommandException:
                if(print_error == True):
                    self.log(str(t.result), self.ERROR)

                raise RemoteCommandException
            
            if(stdout_only == True):    
                results.append(t.result[1].read())
            else:
                results.append(t.result)
            
            self.log(t.result[1].read(), self.INFO)

        return results
    

    def client_remote_command(self, client, command):
        self.log(client.hostname + ': Executing ' + command, self.DEBUG)

        prepend = ''

        if 'env' in self.config:
            for var in self.config['env']:
                prepend += 'export ' + var + '=' + self.config['env'][var] + '; '

        stdin, stdout, stderr = client.exec_command(prepend + command)

        if(stdout.channel.recv_exit_status() != 0):
            if(self.config['warn_only'] == True):
                message = stderr.read()
                
                if message != '':
                    self.log(message.decode('utf-8'), self.WARN)
            else:
                errdata = stderr.read()

                if(type(errdata) == bytes):
                    errdata = errdata.decode('utf-8')

                return RemoteCommandException('Remote command error: ' + errdata)

        return stdin, stdout, stderr

    
    def download(self, source, destination):
        for c in self.clients:
            self.log(c.hostname + ': Downloading ' + destination + ' < ' + source, self.DEBUG)
            sftp_client = c.open_sftp()
            sftp_client.get(source, destination)
            sftp_client.close()

    
    def upload(self, source, destination):
        for c in self.clients:
            self.log(c.hostname + ': Uploading ' + source + ' > ' + destination, self.DEBUG)
            sftp_client = c.open_sftp()
            sftp_client.put(source, destination)
            sftp_client.close()


    def upload_template(self, source, destination, params):
        with open(source) as f:
            t = Template(f.read())
            data = t.render(params)
            
        for c in self.clients:
            self.log(c.hostname + ': Uploading ' + source + ' > ' + destination, self.DEBUG)
            sftp_client = c.open_sftp()
            sftp_client.open(destination, "w").write(data)
            sftp_client.close()
    

    def local_command(self, command):
        self.log('Local > ' + command, self.DEBUG)
        popen = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE)
        result = popen.communicate()

        if popen.returncode == 1:
            raise CommandException

        return result[0]

    
    def remote_dir_exists(self, dir):
        try:
            self.remote_command('[[ -d ' + dir + ' ]]', stdout_only = False, print_error = False)
        except RemoteCommandException:
            return False

        return True
    
    
    def remote_file_exists(self, file):
        try:
            self.remote_command('[[ -f ' + file + ' ]]', stdout_only = False, print_error = False)
        except RemoteCommandException:
            return False
        
        return True
        
    
    def rm(self, p, recursive=True):
        if recursive:
            self.remote_command('rm -rf ' + p)
        else:
            self.remote_command('rm ' + p)


    def log(self, message, level):
        if(type(message) == bytes):
            message = message.decode('utf-8')

        if message == '':
            return

        if level <= self.verbose:
            if level == 0:
                print(red(message))
            if level == 1:
                print(yellow(message))
            if level == 2:
                print(green(message))
            if level == 3:
                print(message)


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
