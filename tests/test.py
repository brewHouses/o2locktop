#!/usr/bin/env python3
#encoding:utf-8
# some error may caused by too much connection to the remote server
import sys
import os
import argparse
import logging
import random
import time
import subprocess
import signal
from multiprocessing import Process, Value

DEBUG = True
PY2 = (sys.version_info[0] == 2)
TOTAL = 0
LS_FLAG = Value('d', 1)
FILE_PATH = os.path.abspath(os.path.dirname(__file__))

# set stdin to line buffer
sys.stdin = os.fdopen(sys.stdin.fileno(), 'r', 1)


if not PY2:
    from goto import with_goto

def set_log_file(filename=None):
    if not filename:
        if not os.path.exists('/tmp/log/o2locktop'):
            os.system("mkdir -p /tmp/log/o2locktop")
        logging.basicConfig(filename='/tmp/log/o2locktop/test.log',
                            filemode='w',
                            format='%(levelname)s - %(message)s',
                            level=logging.DEBUG)
    else:
        logging.basicConfig(filename=filename,
                            filemode='w',
                            format='%(levelname)s - %(message)s',
                            level=logging.DEBUG)


LOCKTYPE = ['M', 'W', 'O', 'N', 'S']


def use_logging():
    def decorator(func):
        def wrapper(*args, **kwargs):
            if DEBUG:
                print(args[0])
            return func(*args, **kwargs)
        return wrapper
    return decorator


@use_logging()
def log_err(msg):
    logging.error(msg)


@use_logging()
def log_info(msg):
    logging.info(msg)


def got_eof():
    def decorator(func):
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except EOFError:
                print("got eof, and exit...")
                global LS_FLAG
                LS_FLAG.value = 0
                #pass
                sys.exit(0)
        return wrapper
    return decorator


def create_file(mount_point, creat_file_num=1000):
    global NODE_LIST
    if not NODE_LIST:
        for i in range(creat_file_num):
            newfile = "{0}.test".format(i)
            filepath = os.path.join(mount_point, newfile)
            if not NODE_LIST:
                if not os.path.exists(filepath):
                    os.system("touch {0}".format(filepath))
    else:
        os.system(r'ssh root@{0} "cd {1}; for i in \`seq 0 1000\`; do touch \$i.test; done"'
                  .format(NODE_LIST[0], mount_point))

USAGE = "Enter q to quit"

def parse_args():
    parser = argparse.ArgumentParser(usage=USAGE, prog='o2locktop_test', add_help=True)
    parser.add_argument('-l', metavar='the output length of o2loctop', dest='length',
                        type=int, required=True,
                        action='store',
                        help='number of the entry that o2locktop output')
    parser.add_argument('-d', metavar='the day of the o2loctop test to run', dest='days',
                        type=float, default=0.025,
                        action='store',
                        help='number of the entry that o2locktop output')
    parser.add_argument('-o', metavar='the log file that the test will use', dest='log_file',
                        type=str, action='store',
                        help='the log file that the test will use')
    parser.add_argument('mount_point', nargs='?',
                        help='mount point like /mnt/ocfs2')
    parser.add_argument('-n', metavar='NODE_IP',
                        dest='host_list', action='append',
                        help='OCFS2 node IP address for ssh, the same as o2locktop')
    args = parser.parse_args()
    if not args.mount_point:
        print("you must input the mount point")
        # cause don't have the mount point, it will kill all the o2loctop process in the machine
        kill_o2locktop()
        sys.exit(0)
    if args.mount_point[-1] == '/':
        args.mount_point = args.mount_point[:-1]
    set_log_file(filename=args.log_file)
    node_list = []
    if args.host_list:
        for i in args.host_list:
            node_list.append(i)

    return {'length': args.length,
            'mount_point': args.mount_point,
            'days': args.days,
            'node_list': node_list}


def init():
    args = parse_args()
    return args['length'], args['mount_point'], args['days'], args['node_list']


def get_max_inode(mount_point):
    global NODE_LIST
    if not NODE_LIST:
        cmd = 'df -i | grep "{0}$"'.format(mount_point)
    else:
        cmd = 'ssh root@{0} df -i | grep "{1}$"'.format(NODE_LIST[0], mount_point)
    with os.popen(cmd) as fs_info_fp:
        fs_info = fs_info_fp.read()
        if not fs_info:
            log_err("can't get the max inode according to the mount_point")
            kill_o2locktop(mount_point)
            sys.exit(0)
        else:
            return int(fs_info.strip().split()[1])

def get_uuid(mount_point):
    global NODE_LIST
    #print(node_list)
    if not NODE_LIST:
        with os.popen("o2info --volinfo {0} | grep UUID".format(mount_point)) as filep:
            info = filep.read()
            if not info:
                log_err("can't get the uuid according to the mount_point")
                kill_o2locktop(mount_point)
                sys.exit(0)
            return info.strip().split()[1]
    else:
        with os.popen("ssh root@{0} o2info --volinfo {1} | grep UUID"
                      .format(NODE_LIST[0], mount_point)) as filep:
            info = filep.read()
            if not info:
                log_err("can't get the uuid according to the mount_point")
                kill_o2locktop(mount_point)
                sys.exit(0)
            return info.strip().split()[1]


def remove_clear(line):
    #return line.replace("^[[H^[[2J^[[3J", "")
    return line.replace("\x1b[H\x1b[2J\x1b[3J", "").replace("\x1b[3J\x1b[H\x1b[2J", "")


def not_negative(num):
    try:
        flag = int(num) >= 0
        if not flag:
            log_err("got a negative number in the output, the negative number is {0}"
                    .format(str(num)))
            return False
    except ValueError:
        log_err("got a wrong format of lock number in the output, the wrong format number is {0}"
                .format(num))
        return False
    return True


def test_line(key_word):
    def test(line, key_word=key_word):
        return key_word in line
    return test


is_first_line = test_line('o2locktop')
is_second_line = test_line('acquisitions')
is_third_line = test_line('resources')
is_head_line = test_line('TIME(us)')

@got_eof()
def get_line_type(line=None):
    if not line:
        if PY2:
            raw_line = raw_input()
        else:
            raw_line = input()
        line = remove_clear(raw_line)
        # print(line)
    if is_first_line(line):
        return 'first', line, 0
    if is_second_line(line):
        return 'second', line, 1
    if is_third_line(line):
        return 'third', line, 2
    if is_head_line(line):
        return 'head', line, 3
    line_array = line.strip().split()
    if len(line_array) == 8 and\
       line_array[0].isalpha() and\
       line_array[1].replace('-', '').isdigit() and\
       line_array[2].replace('-', '').isdigit() and\
       line_array[3].replace('-', '').isdigit() and\
       line_array[4].replace('-', '').isdigit() and\
       line_array[5].replace('-', '').isdigit() and\
       line_array[6].replace('-', '').isdigit() and\
       line_array[7].replace('-', '').isdigit():
        return 'locks', line, 4
    if not line.strip():
        return 'blank', line, 5
    # print("got an unknow line")
    return 'unknown', line, 5



@got_eof()
def handle_first_line(uuid, line=None):
    if line == None:
        if PY2:
            raw_line = raw_input()
        else:
            raw_line = input()
        line = remove_clear(raw_line)
        if not is_first_line(line):
            return False
    line = line.strip().split()
    if len(line) != 5:
        log_err("the first line format is wrong, the elements of the line shoule be 5, but is {0}"
                .format(len(line)))
        return False
    if uuid != line[-1]:
        log_err("the uuid not match, should be {0}, but {1}".format(uuid, line[-1]))
        return False
    return True


@got_eof()
def handle_second_line(line=None):
    if line == None:
        # raw_line = raw_input()
        if PY2:
            raw_line = raw_input()
        else:
            raw_line = input()
        line = remove_clear(raw_line)
        if not is_second_line(line):
            return False
    line = line.strip().split()
    if len(line) != 10:
        log_err("the second line format is wrong, the elements of the line shoule be 10, but is {0}"
                .format(len(line)))
        return False
    return int(line[5].replace(",", "")) + 1


@got_eof()
def handle_third_line(line=None):
    if line == None:
        # raw_line = raw_input()
        if PY2:
            raw_line = raw_input()
        else:
            raw_line = input()
        line = remove_clear(raw_line)
        if not is_third_line(line):
            return False
    # line = line.replace("\x1b[3J\x1b[H\x1b[2J", '')
    line = line.replace('\n', ' ')
    line = line.strip().split()
    if not line:
        log_err("can't get the third line")
    if len(line) < 4:
        if PY2:
            raw_line = raw_input()
        else:
            raw_line = input()
        line = remove_clear(raw_line)
        line = line.strip().split()
        if len(line) < 4:
            log_err("the third line format is wrong, "
                    "the elements of the line shoule be bigger than 4, but is {0}"
                    .format(len(line)))
    return int(line[3].replace(",", "")) + 1


@got_eof()
def handle_blank_space():
    # raw_line = raw_input()
    if PY2:
        raw_line = raw_input()
    else:
        raw_line = input()
    line = remove_clear(raw_line)
    line = line.strip()
    if line:
        log_err("get blank space wrong")
        return False
    return True


@got_eof()
def handle_head(line=None):
    if not line:
        # raw_line = raw_input()
        if PY2:
            raw_line = raw_input()
        else:
            raw_line = input()
        line = remove_clear(raw_line)
        if not is_head_line(line):
            return False
    line = line.strip()
    if not line:
        log_err("get blank space wrong")
        return False
    if line.replace(" ", "") != "TYPEINOEXNUMEXTIME(us)EXAVG(us)PRNUMPRTIME(us)PRAVG(us)":
        log_err("get head wrong")
        return False
    return True


@got_eof()
def handle_one_line(max_inode, line=None):
    if not line:
        # raw_line = raw_input()
        if PY2:
            raw_line = raw_input()
        else:
            raw_line = input()
        line = remove_clear(raw_line)
    line = line.strip().split()
    if len(line) != 8:
        log_err("the output line format is wrong, the elements of the line shoule be 8, but is {0}"
                .format(len(line)))
        return False
    #type_ = line[0]
    inode = int(line[1])
    locks = line[2:]
    if False in map(not_negative, locks):
        log_err("have negative or ileagall data in the data, the wrong line is :\n{0}"
                .format(raw_line))
        return False
    if inode > max_inode:
        log_err("the inode is too big : {0}, the max inode should be {1}".format(inode, max_inode))
        return False
    if inode <= 0:
        log_err("the inode is illegal(too small): {0}".format(inode))
        return False
    return True


@got_eof()
def consume_any_line(line=None):
    if not line:
        # raw_line = raw_input()
        if PY2:
            _ = raw_input()
        else:
            _ = input()
    '''
    line = remove_clear(raw_line)
    line = line.strip()
    if "o2locktop" in line:
        return line
    return False
    '''
if not PY2:
    @with_goto
    def test_one_fram(length, mount_point):
        global TOTAL
        '''
        handle_functions = [handle_first_line, handle_second_line,
                            handle_third_line, handle_head,
                            handle_one_line, consume_any_line]
        '''

        uuid = get_uuid(mount_point)
        max_inode = get_max_inode(mount_point)
        while True:
            info = get_line_type()
            if info[0] == "first":
                handle_first_line(uuid, info[1])
                goto .first
            elif info[0] == "second":
                TOTAL = handle_second_line(info[1])
                goto .second
            elif info[0] == "third":
                handle_third_line(info[1])
                goto .third
            elif info[0] == "blank":
                # handle_blank_space()
                goto .blank
            elif info[0] == "head":
                handle_head(info[1])
                goto .head
            elif info[0] == "locks":
                handle_one_line(max_inode, info[1])
                goto .head
            # if is "unknown", then loop
        handle_first_line(uuid)
        label .first
        TOTAL = handle_second_line()
        label .second
        handle_third_line()
        label .third
        handle_blank_space()
        label .blank
        handle_head()
        label .head
        for _ in range(length + 1):
            info = get_line_type()
            if info[0] == "locks":
                handle_one_line(max_inode, info[1])
            else:
                break
else:
    def test_one_fram(length, mount_point):
        global TOTAL
        '''
        handle_functions = [handle_first_line, handle_second_line,
                            handle_third_line, handle_head,
                            handle_one_line, consume_any_line]
        '''

        uuid = get_uuid(mount_point)
        max_inode = get_max_inode(mount_point)
        while True:
            info = get_line_type()
            if info[0] == "first":
                handle_first_line(uuid, info[1])
            elif info[0] == "second":
                TOTAL = handle_second_line(info[1])
            elif info[0] == "third":
                handle_third_line(info[1])
            elif info[0] == "blank":
                # handle_blank_space()
                continue
            elif info[0] == "head":
                handle_head(info[1])
            elif info[0] == "locks":
                handle_one_line(max_inode, info[1])
                break
            if "unknown" in info[0]:
                return
        # maybe change "length + 1" to "length" could correct the logic wrong
        for _ in range(length + 1):
            info = get_line_type()
            if info[0] == "locks":
                handle_one_line(max_inode, info[1])
            else:
                break

def dynamics_test(length, mount_point, node_list):
    global TOTAL, LS_FLAG
    total_list = []
    if not node_list:
        test_one_fram(length, mount_point)
        total1 = TOTAL
        # ls_flag = Value('d', 1)
        LS_FLAG.value = 1
        process = Process(target=ls_loop, args=(mount_point, LS_FLAG))
        process.start()
        if PY2:
            test_one_fram(length, mount_point)
            total_list.append(TOTAL)
            test_one_fram(length, mount_point)
            total_list.append(TOTAL)
        test_one_fram(length, mount_point)
        total_list.append(TOTAL)
        test_one_fram(length, mount_point)
        total_list.append(TOTAL)
        test_one_fram(length, mount_point)
        total_list.append(TOTAL)
        test_one_fram(length, mount_point)
        total_list.append(TOTAL)
        LS_FLAG.value = 0
        process.join()
        flag = False
        for i in total_list:
            if total1 < i:
                log_info("\033[1;32mlocal mode dynamics_test OK, the total = {0}, total2 = {1} \033[0m"
                         .format(total1, i))
                flag = True
                break
        if not flag:
            log_err("\033[1;31mlocal modedynamics_test failed, the total1 = {0}, total2 = {1}\033[0m"
                    .format(total1, TOTAL))
    else:
        test_one_fram(length, mount_point)
        total1 = TOTAL
        # ls_flag = Value('d', 1)
        LS_FLAG.value = 1
        for node in node_list:
            process = Process(target=ls_loop_on_node, args=(mount_point, node))
            process.start()
        if PY2:
            test_one_fram(length, mount_point)
            total_list.append(TOTAL)
            test_one_fram(length, mount_point)
            total_list.append(TOTAL)
        test_one_fram(length, mount_point)
        total_list.append(TOTAL)
        test_one_fram(length, mount_point)
        total_list.append(TOTAL)
        test_one_fram(length, mount_point)
        total_list.append(TOTAL)
        test_one_fram(length, mount_point)
        total_list.append(TOTAL)
        LS_FLAG.value = 0
        process.join()
        flag = False
        max_lock_num = max(total_list)
        if total1 < max_lock_num:
            log_info("\033[1;32mremote mode dynamics_test OK, the total = {0}, total2 = {1} \033[0m"
                     .format(total1, max_lock_num))
            flag = True
        if not flag:
            log_err("\033[1;31mremote mode dynamics_test failed, the total1 = {0}, total2 = {1}\033[0m"
                    .format(total1, TOTAL))



def static_test(length, mount_point):
    global TOTAL
    test_one_fram(length, mount_point)
    total1 = TOTAL
    test_one_fram(length, mount_point)
    total2 = TOTAL
    if total1 * 1.1 >= total2 and total1 * 0.9 <= total2:
        log_info("static_test OK,the total1 = {0}, total2 = {1}"
                 .format(total1, total2))
    else:
        log_err("static_test failed,the total1 = {0}, total2 = {1}"
                .format(total1, total2))


def ls_loop(mount_point, ls_flag):
    with open(os.path.join(FILE_PATH, 'list_file.sh'), 'w') as sh_script:
        sh_script.write("#!/bin/bash\n")
        sh_script.write("while true\n")
        sh_script.write("do\n")
        sh_script.write("ls -l {0}\n".format(mount_point))
        sh_script.write("sleep 0.1\n")
        sh_script.write("done\n")

    stf_p = subprocess.Popen(os.path.join(FILE_PATH, 'list_file.sh'),
                             stdout=open('/dev/null', 'w'),
                             stderr=open('/dev/null', 'w'))
    # stf_p = subprocess.Popen([os.path.join(file_path, 'list_file.sh'), mount_point])
    while ls_flag.value:
        time.sleep(0.5)
    stf_p.kill()


def ls_loop_on_node(mount_point, node):
    with open(os.path.join(FILE_PATH, 'list_file.sh'), 'w') as sh_script:
        sh_script.write("#!/bin/bash\n")
        sh_script.write("for i in `seq 1 80`\n")
        sh_script.write("do\n")
        sh_script.write("ls -l {0} > /dev/null\n".format(mount_point))
        sh_script.write("sleep 0.1\n")
        sh_script.write("done\n")
    '''
    subprocess.call('scp {file_name} root@{node}:/tmp'.format(file_name=\
        os.path.join(FILE_PATH, 'list_file.sh'), node=node))
    subprocess.call('ssh root@{node} "chmod u+x /tmp/list_file.sh"'.format(node=node))
    subprocess.call('ssh root@{node} /tmp/list_file.sh > /dev/null'.format(node=node))
    '''
    devnull = open('/dev/null', 'w')
    subprocess.call(['scp',
                     os.path.join(FILE_PATH, 'list_file.sh'),
                     'root@{node}:/tmp'.format(node=node)],
                    stdout=devnull)
    os.popen('ssh root@{node} "chmod u+x /tmp/list_file.sh"'.format(node=node))
    os.popen('ssh root@{node} /tmp/list_file.sh > /dev/null'.format(node=node))
    devnull.close()

def kill_o2locktop(mount_point=None):
    if mount_point != None:
        cmd = 'ps aux |grep o2locktop |grep {0}'.format(mount_point)
        with os.popen(cmd) as processes:
            for process in processes.read().strip().split('\n'):
                #print(process)
                #os.kill(int(process.strip().split()[1]), signal.SIGKILL)
                try:
                    os.kill(int(process.strip().split()[1]), 0)
                except ProcessLookupError:
                    continue
                os.kill(int(process.strip().split()[1]), signal.SIGKILL)
            sys.exit(0)
    else:
        cmd = 'ps aux |grep o2locktop'
        with os.popen(cmd) as processes:
            for process in processes.read().strip().split('\n'):
                #print(process)
                try:
                    os.kill(int(process.strip().split()[1]), 0)
                except ProcessLookupError:
                    continue
                os.kill(int(process.strip().split()[1]), signal.SIGKILL)
            sys.exit(0)

NODE_LIST = []
def run():
    global NODE_LIST
    length, mount_point, days, NODE_LIST = init()
    create_file(mount_point)
    i = 0
    loop_times = days * 17280
    index = 0
    while True:
        index += 1
        if index%10 == 2:
            if DEBUG:
                print("d test")
            dynamics_test(length, mount_point, NODE_LIST)
        elif random.randint(1, 10) == 2:
            # print("s test")
            # static_test(length, mount_point)
            pass
        test_one_fram(length, mount_point)
        i += 1
        if i > loop_times:
            kill_o2locktop(mount_point)

if __name__ == '__main__':
    run()
