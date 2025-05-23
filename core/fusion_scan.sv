module fusion_scan
  import ariane_pkg::*;
#(
    parameter config_pkg::cva6_cfg_t CVA6Cfg = config_pkg::cva6_cfg_empty,
    parameter type branchpredict_sbe_t = logic,
    parameter type exception_t = logic,
    parameter type scoreboard_entry_t = logic
) (
    input scoreboard_entry_t [1:0] instruction_i, // Instructions from decoders
    input logic [1:0] fetch_entry_valid_i, // Valid from frontend
    output scoreboard_entry_t [1:0] instruction_o, // Fused or propagated instructions
    output logic fusion_second_instr_valid_o // Is the first instruction valid ? Second instruction is always valid
);

logic [2:0] pc_offset;

always_comb begin
    // Default case: propagate the two instructions
    instruction_o[0] = instruction_i[0];
    instruction_o[1] = instruction_i[1];
    fusion_second_instr_valid_o = 1'b1;
    pc_offset = 3'b000;
    // Check for fusion opportunities 
    if ((instruction_i[0].rd == instruction_i[1].rs1) && (instruction_i[0].rd == instruction_i[1].rd) && instruction_i[0].ex.valid == 1'b0 && instruction_i[1].ex.valid == 1'b0 && fetch_entry_valid_i == 2'b11) begin
        
        case (instruction_i[0].op)
            ariane_pkg::ADD:
                case (instruction_i[1].op)
                    ariane_pkg::LD, ariane_pkg::LB, ariane_pkg::LBU, ariane_pkg::LH, ariane_pkg::LHU, ariane_pkg::LW, ariane_pkg::LWU: begin

                        // ADD operands are fused with the LOAD scoreboard_entry on the first instruction port
                        instruction_o[0] = instruction_i[1];
                        instruction_o[0].rs1 = instruction_i[0].rs1;
                        instruction_o[0].rs2 = instruction_i[0].rs2;

                        if (instruction_i[0].use_imm && instruction_i[0].use_pc) begin
                            instruction_o[0].use_pc = instruction_i[0].use_pc;
                            if (instruction_i[0].is_compressed) begin
                                pc_offset = 3'b010;
                            end else begin
                                pc_offset = 3'b100;
                            end
                        end

                        // Immediate from ADDI or AUIPC is summed with LOAD immediate
                        if (instruction_i[0].use_imm) begin
                            instruction_o[0].result = $signed($signed(instruction_i[0].result[32:0]) + $signed(instruction_i[1].result[32:0]) - pc_offset);
                        end

                        // second istruction scoreboard_entry is invalidated
                        fusion_second_instr_valid_o = 1'b0;

                        // The two is_compressed fields are encoded inside is_fusion
                        case ({instruction_i[0].is_compressed, instruction_i[1].is_compressed})
                            2'b11:
                                instruction_o[0].is_fusion = 2'b01; 
                            2'b01, 2'b10:
                                instruction_o[0].is_fusion = 2'b10; 
                            2'b00:
                                instruction_o[0].is_fusion = 2'b11; 
                        endcase
                    end
                endcase
        endcase
    end
end

endmodule
