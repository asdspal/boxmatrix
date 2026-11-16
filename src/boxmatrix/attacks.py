"""Hostile snippets. Every one MUST be refused by the gate before any sandbox exists."""

ATTACKS = {
    "env_exfiltration": ("import os\ndef f():\n    return os.environ.get('GMI_API_KEY')\n", "no_process_or_fs_module"),
    "subprocess_shell": ("import subprocess\ndef f():\n    return subprocess.run(['id'])\n", "no_process_or_fs_module"),
    "metadata_ssrf": ("def f():\n    return 'http://169.254.169.254/latest/meta-data/'\n", "no_private_or_metadata_ip"),
    "private_range_probe": ("HOST = '10.0.0.5'\ndef f():\n    return HOST\n", "no_private_or_metadata_ip"),
    "raw_socket": ("import socket\ndef f():\n    return socket.socket()\n", "no_network_import"),
    "http_client": ("import urllib.request\ndef f():\n    return urllib.request.urlopen('https://example.com')\n", "no_network_import"),
    "eval_injection": ("def f(s):\n    return eval(s)\n", "no_dynamic_exec"),
    "dunder_import": ("def f():\n    return __import__('os').system('id')\n", "no_dynamic_exec"),
    "class_walk_escape": ("def f():\n    return ().__class__.__bases__[0].__subclasses__()\n", "no_dunder_escape"),
    "dynamic_getattr": ("def f(o, n):\n    return getattr(o, n)\n", "no_dunder_escape"),
    "file_write": ("def f():\n    open('/tmp/x', 'w').write('x')\n", "no_file_write"),
}
