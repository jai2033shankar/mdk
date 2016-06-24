#!python

import sys

from mdk import SharedContext

class TestState (object):
    def __init__(self, gold):
        self.gold = gold
        self.goldline = 0
        self.mismatch = False

    def log(self, ctx, msg):
        ctx.tick();
    
        text = "%s -- %s" % (ctx.key(), msg)

        marker = ' '
        wanted = None

        if self.goldline >= len(self.gold):
            marker = '+'
            self.mismatch = True
        elif text != self.gold[self.goldline]:
            marker = '!'
            wanted = self.gold[self.goldline]
            self.mismatch = True
        else:
            self.goldline += 1

        print("%s %s" % (marker, text))

        if wanted:
            print("W %s" % wanted)

    def enter(self, ctx, ctxName):
        c2 = ctx.enter();
        self.log(c2, "entered %s" % ctxName);
        return c2

    def leave(self, ctx, ctxName):
        self.log(ctx, "leaving %s" % ctxName);
        return ctx.leave();

Tests = [
    [ "simple",
        [
            'create t1',
            'step t1',
            'step t1',
            'step t1',
            'done t1',
        ],
        [
            'simple-t1:1 -- CREATED t1',
            'simple-t1:2 -- step t1',
            'simple-t1:3 -- step t1',
            'simple-t1:4 -- step t1',
            'simple-t1:5 -- done',
        ]        

    ],
    [ "linear",
        [
            'create t1',
            'step t1',
            'enter t1 t2',
            'step t2',
            'leave t2',
            'enter t1 t3',
            'step t3',
            'leave t3',
            'done t1',
        ],
        [
            'linear-t1:1 -- CREATED t1',
            'linear-t1:2 -- step t1',
            'linear-t1:3,1 -- entered t2',
            'linear-t1:3,2 -- step t2',
            'linear-t1:3,3 -- leaving t2',
            'linear-t1:4,1 -- entered t3',
            'linear-t1:4,2 -- step t3',
            'linear-t1:4,3 -- leaving t3',
            'linear-t1:5 -- done',
        ]
    ],
    [ "descend",
        [
            'create t1',
            'step t1',
            'enter t1 t2',
            'step t2',
            'enter t2 t3',
            'step t3',
            'enter t3 t4',
            'step t4',
            'leave t4',
            'leave t3',
            'leave t2',
            'done t1',
        ],
        [
            'descend-t1:1 -- CREATED t1',
            'descend-t1:2 -- step t1',
            'descend-t1:3,1 -- entered t2',
            'descend-t1:3,2 -- step t2',
            'descend-t1:3,3,1 -- entered t3',
            'descend-t1:3,3,2 -- step t3',
            'descend-t1:3,3,3,1 -- entered t4',
            'descend-t1:3,3,3,2 -- step t4',
            'descend-t1:3,3,3,3 -- leaving t4',
            'descend-t1:3,3,4 -- leaving t3',
            'descend-t1:3,4 -- leaving t2',
            'descend-t1:4 -- done',
        ]
    ],
    [ "parallel",
        [
            'create t1',
            'step t1',
            'enter t1 t2',
            'enter t1 t3',
            'enter t1 t4',
            'step t2',
            'step t3',
            'step t4',
            'step t2',
            'step t3',
            'step t4',
            'leave t2',
            'leave t3',
            'leave t4',
            'done t1',
        ],
        [
            'parallel-t1:1 -- CREATED t1',
            'parallel-t1:2 -- step t1',
            'parallel-t1:3,1 -- entered t2',
            'parallel-t1:4,1 -- entered t3',
            'parallel-t1:5,1 -- entered t4',
            'parallel-t1:3,2 -- step t2',
            'parallel-t1:4,2 -- step t3',
            'parallel-t1:5,2 -- step t4',
            'parallel-t1:3,3 -- step t2',
            'parallel-t1:4,3 -- step t3',
            'parallel-t1:5,3 -- step t4',
            'parallel-t1:3,4 -- leaving t2',
            'parallel-t1:4,4 -- leaving t3',
            'parallel-t1:5,4 -- leaving t4',
            'parallel-t1:6 -- done',
        ]
    ],
    [ "combined",
        [
            'create t1',
            'step t1',
            'enter t1 t2',
            'enter t1 t3',
            'step t2',
            'step t2',
            'step t3',
            'step t3',
            'enter t2 t2-1',
            'step t2-1',
            'step t2',
            'step t3',
            'step t2-1',
            'enter t3 t3-1',
            'enter t2-1 t2-1-1',
            'step t2-1-1',
            'step t3',
            'step t2-1-1',
            'leave t2-1-1',
            'step t3',
            'leave t2-1',
            'step t3',
            'enter t3 t3-1',
            'step t2',
            'leave t2',
            'step t3-1',
            'step t3-1',
            'leave t3-1',
            'leave t3',
            'step t1',
            'done t1',
        ],
        [
            'combined-t1:1 -- CREATED t1',
            'combined-t1:2 -- step t1',
            'combined-t1:3,1 -- entered t2',
            'combined-t1:4,1 -- entered t3',
            'combined-t1:3,2 -- step t2',
            'combined-t1:3,3 -- step t2',
            'combined-t1:4,2 -- step t3',
            'combined-t1:4,3 -- step t3',
            'combined-t1:3,4,1 -- entered t2-1',
            'combined-t1:3,4,2 -- step t2-1',
            'combined-t1:3,5 -- step t2',
            'combined-t1:4,4 -- step t3',
            'combined-t1:3,4,3 -- step t2-1',
            'combined-t1:4,5,1 -- entered t3-1',
            'combined-t1:3,4,4,1 -- entered t2-1-1',
            'combined-t1:3,4,4,2 -- step t2-1-1',
            'combined-t1:4,6 -- step t3',
            'combined-t1:3,4,4,3 -- step t2-1-1',
            'combined-t1:3,4,4,4 -- leaving t2-1-1',
            'combined-t1:4,7 -- step t3',
            'combined-t1:3,4,5 -- leaving t2-1',
            'combined-t1:4,8 -- step t3',
            'combined-t1:4,9,1 -- entered t3-1',
            'combined-t1:3,6 -- step t2',
            'combined-t1:3,7 -- leaving t2',
            'combined-t1:4,9,2 -- step t3-1',
            'combined-t1:4,9,3 -- step t3-1',
            'combined-t1:4,9,4 -- leaving t3-1',
            'combined-t1:4,10 -- leaving t3',
            'combined-t1:5 -- step t1',
            'combined-t1:6 -- done',
        ]
    ],
]

errors = 0

for name, vectors, gold in Tests:
    contexts = {}
    state = TestState(gold)

    print("START %s" % name)

    for vector in vectors:
        fields = vector.split(' ')

        cmd = fields.pop(0)

        if cmd == 'create':
            ctxID = fields[0]
            originID = '%s-%s' % (name, ctxID)

            contexts[ctxID] = SharedContext.withOrigin(originID)
            state.log(contexts[ctxID], "CREATED %s" % ctxID)
        elif cmd == 'step':
            ctxID = fields[0]
            state.log(contexts[ctxID], "step %s" % ctxID)
        elif cmd == 'enter':
            ctxID1 = fields[0]
            ctxID2 = fields[1]

            contexts[ctxID2] = state.enter(contexts[ctxID1], ctxID2)
        elif cmd == 'leave':
            ctxID = fields[0]
            state.leave(contexts[ctxID], ctxID)
        elif cmd == 'done':
            ctxID = fields[0]
            state.log(contexts[ctxID], "done")

            if state.mismatch:
                print("FAIL %s" % name)
                errors += 1
            else:
                print("GOOD %s" % name)
            break

sys.exit(errors)

