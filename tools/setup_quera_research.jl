# Instantiate the qualified forward environment without changing its dependency lock.
using SHA
@assert VERSION == v"1.11.3"
project = abspath(ARGS[1])
lock = joinpath(project, "Manifest.toml")
expected = "3b1cdef37a183be5822a4e3032fa3125ad3dee70ec231c387791c036bdbd2f81"
@assert bytes2hex(sha256(read(lock))) == expected
using Pkg
@assert abspath(dirname(Base.active_project())) == project
Pkg.instantiate()
using DiffABM, Images
@assert bytes2hex(sha256(read(lock))) == expected
println("Qualified Julia forward environment ready")
