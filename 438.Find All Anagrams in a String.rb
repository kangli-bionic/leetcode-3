# @param {String} s
# @param {String} p
# @return {Integer[]}
def find_anagrams(s, p)
    counter = Hash.new(0)
    for c in p.each_char
        counter[c] += 1
    end
    unmatched = counter.size
    res = []
    for r in (0...s.size)
        counter[s[r]] -= 1
        unmatched -= 1 if counter[s[r]] == 0
        unmatched += 1 if counter[s[r]] == -1
        if r >= p.size
            l = r - p.size
            counter[s[l]] += 1
            unmatched -= 1 if counter[s[l]] == 0
            unmatched += 1 if counter[s[l]] == 1
        end
        res << r - p.size + 1 if r >= p.size - 1 && unmatched == 0
    end
    res
end
