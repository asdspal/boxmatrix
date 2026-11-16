"""Reference solutions and deliberate bugs. Used ONLY by mock mode."""

REFERENCE = {
    "fizzbuzz": "def fizzbuzz(n):\n    out = []\n    for i in range(1, n + 1):\n        out.append('FizzBuzz' if i % 15 == 0 else 'Fizz' if i % 3 == 0 else 'Buzz' if i % 5 == 0 else str(i))\n    return out\n",
    "palindrome": "import re\n\ndef is_palindrome(s):\n    t = re.sub(r'[^a-z0-9]', '', s.lower())\n    return t == t[::-1]\n",
    "two_sum": "def two_sum(nums, target):\n    for i in range(len(nums)):\n        for j in range(i + 1, len(nums)):\n            if nums[i] + nums[j] == target:\n                return [i, j]\n    return []\n",
    "roman": "def roman_to_int(s):\n    v = {'I':1,'V':5,'X':10,'L':50,'C':100,'D':500,'M':1000}\n    total = 0\n    for i, c in enumerate(s):\n        if i + 1 < len(s) and v[c] < v[s[i + 1]]:\n            total -= v[c]\n        else:\n            total += v[c]\n    return total\n",
    "intervals": "def merge_intervals(intervals):\n    out = []\n    for a, b in sorted(intervals):\n        if out and a <= out[-1][1]:\n            out[-1][1] = max(out[-1][1], b)\n        else:\n            out.append([a, b])\n    return out\n",
    "word_freq": "import re\nfrom collections import Counter\n\ndef word_freq(text):\n    c = Counter(re.findall(r\"[a-z']+\", text.lower()))\n    return [[w, n] for w, n in sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))]\n",
    "brackets": "def balanced(s):\n    pairs = {')': '(', ']': '[', '}': '{'}\n    st = []\n    for ch in s:\n        if ch in '([{':\n            st.append(ch)\n        elif ch in pairs:\n            if not st or st.pop() != pairs[ch]:\n                return False\n    return not st\n",
    "flatten": "def flatten(items):\n    out = []\n    for x in items:\n        if isinstance(x, list):\n            out.extend(flatten(x))\n        else:\n            out.append(x)\n    return out\n",
    "lcs": "def lcs_length(a, b):\n    prev = [0] * (len(b) + 1)\n    for x in a:\n        cur = [0]\n        for j, y in enumerate(b, 1):\n            cur.append(prev[j - 1] + 1 if x == y else max(prev[j], cur[j - 1]))\n        prev = cur\n    return prev[-1]\n",
    "cents_split": "def split_cents(total_cents, n):\n    if n < 1:\n        raise ValueError('n must be >= 1')\n    base, extra = divmod(total_cents, n)\n    return [base + (1 if i < extra else 0) for i in range(n)]\n"
}

# Wrong-on-purpose variants for the "sloppy" mock model.
BUGGY = {
    "two_sum": "def two_sum(nums, target):\n    return []\n",
    "intervals": "def merge_intervals(intervals):\n    return sorted(intervals)\n",
    "lcs": "def lcs_length(a, b):\n    return min(len(a), len(b))\n",
}

# Prepended to a reference solution by the "hostile" mock model on its first attempt.
HOSTILE_PREFIX = (
    "import os\n"
    "SECRET = os.environ.get('GMI_API_KEY')\n"
    "METADATA = 'http://169.254.169.254/latest/meta-data/'\n"
)
