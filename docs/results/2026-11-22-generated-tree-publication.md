# Generated tree publication

`pnpm run gen` generates a complete tree in its temporary project. The
previous Network wrapper removed and recopied the root `gen/` after every
successful call. The new wrapper compares the full completed tree, holds the
project lock during publication, and returns early when the paths, content,
and file modes match.

When the tree changes, the publisher prepares the replacement beside the
target. It links matching files when the filesystem supports hard links and
copies the other files. A rename installs the complete replacement. The old
tree is available for rollback until that rename succeeds. A reader can see a
short interval between the two renames. A forced process stop during that
interval can leave the previous tree inside `.gen-publication-*` for
recovery. A change can update the change time of matching inodes through
hard links. The tests compare output bytes, paths, modes, inode identity, and
modification times.

## Measurements

Warm the formal action cache first. Alternate the old and new wrapper with
`/usr/bin/time -p corepack pnpm@10.24.0 run gen`. Compare the sorted paths and
byte digests of all files below `gen/` after each run. Then compare each
file's inode, mode, and modification time before and after that run.

Five pairs ran with Node 26.13.0 and pnpm 10.24.0 on an 18-core Apple Silicon
host. Both sides produced the same 688 files with a combined SHA-256 of
`e107b82848fbd4399c9d70a56d40a2ac3d5f4af0d6ee26e18e155735b00976f7`.
Each old publication replaced all 688 files. Each new publication preserved
all 688 files and the generated directory itself. Processor medians were
2.75 and 2.59 seconds. Elapsed medians were 2.49 and 2.59 seconds, with
overlapping ranges of 2.45–3.37 and 2.21–2.69 seconds. This is an output-write
reduction. The elapsed timing shows no measurable difference.

The repair run changed the bytes in one published file and the permissions
on another, and added a stale directory and a symbolic link. Generation
reinstated the expected digest, replaced those two files, and removed the
stale entries. The other 686 files kept their inodes and modification times.
A malformed spec returned an error and left the prior tree intact. A
separate test replaced the publication directory with a link to a sentinel
directory, then ran generation. The generated tree returned and the sentinel
directory kept its original contents.

## Alternatives

The original full copy leaves an incomplete tree while the files are being
copied. A file-by-file update keeps the directory in place and can expose a
mix of old and new module versions. Preparing a complete replacement before
publication also keeps file-copy failure away from the installed tree.
