# Forward episode of the pinned author model. No training or gradient adaptation.
using DiffABM
using Images
using Random

project, output, seed_text, horizon_text = ARGS[1:4]
vision, metabolism_alpha, metabolism_beta, wealth_alpha, wealth_beta, regeneration = parse.(Float64, ARGS[5:10])
@assert VERSION == v"1.11.3"
rows = [parse.(Float64, split(line)) for line in readlines(joinpath(project, "scripts/sugar-map.txt"))]
landscape = reduce(vcat, permutedims.(rows))
board_length = 25
board = Images.imresize(landscape, (board_length, board_length))[:]
stored_states = parse(Int, horizon_text) + 1
params = SugarScapeParams(
    GeneratedBoard(board_length, board),
    RandomAgentInitializer(board_length, vision_distribution_probs=[vision, 1 - vision],
        metabolic_rate_bounds=[metabolism_alpha, metabolism_beta], wealth_bounds=[wealth_alpha, wealth_beta],
        neighborhood=VonNeumannNeighborhood(), discrete_sampler=DiffABM.ST(), vision_spacing=5),
    board_length, 100, stored_states, [regeneration], 10000, DiffABM.GaussianSmoothing(1.0))
Random.seed!(parse(Int, seed_text))
history = abm_run(params)
@assert length(history) == 6 && all(length(h) == stored_states for h in history)
boards, xs, ys, wealths, alive, occupied = history
open(joinpath(output, "agents.csv"), "w") do stream
    println(stream, "time,agent,x,y,wealth,alive")
    for time in 1:stored_states, agent in 1:100
        println(stream, join((time - 1, agent, xs[time][agent], ys[time][agent], wealths[time][agent], alive[time][agent]), ","))
    end
end
open(joinpath(output, "cells.csv"), "w") do stream
    println(stream, "time,x,y,sugar,occupied")
    for time in 1:stored_states, x in 1:board_length, y in 1:board_length
        println(stream, join((time - 1, x, y, boards[time][x,y], occupied[time][x,y]), ","))
    end
end
