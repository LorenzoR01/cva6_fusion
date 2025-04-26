module fusion_scan
  import ariane_pkg::*;
#(
    parameter config_pkg::cva6_cfg_t CVA6Cfg = config_pkg::cva6_cfg_empty,
    parameter type branchpredict_sbe_t = logic,
    parameter type exception_t = logic,
    parameter type scoreboard_entry_t = logic
    
) (
    input logic clk_i, // Clock 
    input logic rst_ni, // Reset
    input scoreboard_entry_t [1:0] instruction_i, // Instructions from decoders
    input logic [1:0] fetch_entry_ready_i, // Check for stalls on issue port
    output scoreboard_entry_t [1:0] instruction_o, // Fused or propagated instructions
    output logic first_instruction_valid_o // Is the first instruction valid ? Second instruction is always valid
);

scoreboard_entry_t prev_fusion_inst_q;

always_comb begin
    // Default case: propagate the two instructions
    instruction_o[0] = instruction_i[0];
    instruction_o[1] = instruction_i[1];
    first_instruction_valid_o = 1'b1;

    // Check for fusion opportunities 
    if ((instruction_i[0].rd == instruction_i[1].rs1) && (instruction_i[0].rd == instruction_i[1].rd) && instruction_i[0].use_imm == 1'b0 && instruction_i[0].ex.valid == 1'b0 && instruction_i[1].ex.valid == 1'b0) begin
        
        case (instruction_i[0].op)
            ariane_pkg::ADD:
                case (instruction_i[1].op)
                    ariane_pkg::LD, ariane_pkg::LB, ariane_pkg::LBU, ariane_pkg::LH, ariane_pkg::LHU, ariane_pkg::LW, ariane_pkg::LWU: begin
                        
                        // ADD operands are fused with the LOAD scoreboard_entry
                        instruction_o[1].rs1 = instruction_i[0].rs1;
                        instruction_o[1].rs2 = instruction_i[0].rs2;

                        // ADD scoreboard_entry is invalidated
                        first_instruction_valid_o = 1'b0;

                        // The two is_compressed fields are encoded inside is_fusion
                        case ({instruction_i[0].is_compressed, instruction_i[1].is_compressed})
                            2'b11:
                                instruction_o[1].is_fusion = 2'b01; 
                            2'b01, 2'b10:
                                instruction_o[1].is_fusion = 2'b10; 
                            2'b00:
                                instruction_o[1].is_fusion = 2'b11; 
                        endcase
                    end
                endcase
        endcase
    end

    // Overwrite the current instruction on port 0 if there was a fusion with port 1 stall on the previous cycle
    if (prev_fusion_inst_q.pc == instruction_i[0].pc) begin
        instruction_o[0] = prev_fusion_inst_q;
        first_instruction_valid_o = 1'b1;
        instruction_o[1] = instruction_i[1];
    end
end

always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      prev_fusion_inst_q <= '0;

    // If there is a fusion with stall on port 1 save the fused instruction for the next cycle
    end else if (instruction_o[1].is_fusion != 2'b00 && fetch_entry_ready_i == 2'b01) begin 
      prev_fusion_inst_q <= instruction_o[1];
    
    // Clear the register after it is used
    end else if (instruction_o[0].pc != prev_fusion_inst_q.pc) begin
        prev_fusion_inst_q <= '0;
    end
  end

endmodule