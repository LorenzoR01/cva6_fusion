module fusion_scan
  import ariane_pkg::*;
#(
    parameter config_pkg::cva6_cfg_t CVA6Cfg = config_pkg::cva6_cfg_empty,
    parameter type branchpredict_sbe_t = logic,
    parameter type exception_t = logic,
    parameter type scoreboard_entry_t = logic
) (
    input scoreboard_entry_t [2:0] instruction_i, // Instructions from decoders
    input logic [2:0] fetch_entry_valid_i, // Valid from frontend
    output scoreboard_entry_t [1:0] instruction_o, // Fused or propagated instructions
    output logic second_port_inst_valid_o // Is the second instruction valid ? First instruction is always valid
);

logic [2:0] pc_offset;
scoreboard_entry_t fusion_first_inst, fusion_second_inst, standard_inst;
logic fusion_port;

enum logic [1:0] {
    NOFUSION,
    ADD_LOAD,
    ADDI_ADDI
} fusion_type;

always_comb begin
    fusion_port = 1'b0;
    fusion_type = NOFUSION;
    fusion_first_inst = instruction_i[0];
    fusion_second_inst = instruction_i[1];
    standard_inst = instruction_i[2];
    second_port_inst_valid_o = 1'b1; 
    // Check for fusion opportunities 
    if ((instruction_i[0].rd == instruction_i[1].rs1) && (instruction_i[0].rd == instruction_i[1].rd) && instruction_i[0].ex.valid == 1'b0 && instruction_i[1].ex.valid == 1'b0 && fetch_entry_valid_i[1:0] == 2'b11) begin
        case (instruction_i[0].op)
            ariane_pkg::ADD, ariane_pkg::ADDW:
                case (instruction_i[1].op)
                    // ADD/ADDI/AUIPC + LOAD Fusion
                    ariane_pkg::LD, ariane_pkg::LB, ariane_pkg::LBU, ariane_pkg::LH, ariane_pkg::LHU, ariane_pkg::LW, ariane_pkg::LWU: begin
                        fusion_type = ADD_LOAD;
                    end
                    // AUIPC/ADDI + ADDI Fusion
                    ariane_pkg::ADD, ariane_pkg::ADDW: begin
                        // if first instruction is AUIPC or ADDI and second instruction is ADDI
                        if (instruction_i[0].use_imm && instruction_i[1].use_imm && !instruction_i[1].use_pc) begin
                            fusion_type = ADDI_ADDI;
                        end
                    end
                endcase
        endcase
        if (fusion_type != NOFUSION) begin
            second_port_inst_valid_o = fetch_entry_valid_i[2]; 
        end 
    end
    if ((instruction_i[1].rd == instruction_i[2].rs1) && (instruction_i[1].rd == instruction_i[2].rd) && instruction_i[1].ex.valid == 1'b0 && instruction_i[2].ex.valid == 1'b0 && fetch_entry_valid_i == 3'b111 && fusion_type == NOFUSION) begin
        case (instruction_i[1].op)
            ariane_pkg::ADD, ariane_pkg::ADDW:
                case (instruction_i[2].op)
                    // ADD/ADDI/AUIPC + LOAD Fusion
                    ariane_pkg::LD, ariane_pkg::LB, ariane_pkg::LBU, ariane_pkg::LH, ariane_pkg::LHU, ariane_pkg::LW, ariane_pkg::LWU: begin
                        fusion_type = ADD_LOAD;
                    end
                    // AUIPC/ADDI + ADDI Fusion
                    ariane_pkg::ADD, ariane_pkg::ADDW: begin
                        // if first instruction is AUIPC or ADDI and second instruction is ADDI
                        if (instruction_i[1].use_imm && instruction_i[2].use_imm && !instruction_i[2].use_pc) begin
                            fusion_type = ADDI_ADDI;
                        end
                    end
                endcase
        endcase
        if (fusion_type != NOFUSION) begin
            fusion_first_inst = instruction_i[1];
            fusion_second_inst = instruction_i[2];
            standard_inst = instruction_i[0];
            fusion_port = 1'b1;
        end 
    end
end

always_comb begin
    // Default no fusion: propagate the two instructions
    instruction_o[0] = fusion_first_inst;
    instruction_o[1] = fusion_second_inst;
    pc_offset = 3'b000;

    if (fusion_type != NOFUSION) begin
        
        // first fusion instruction operands are fused with the second fusion instruction scoreboard_entry on the fusion instruction port
        instruction_o[fusion_port] = fusion_second_inst;
        instruction_o[fusion_port].rs1 = fusion_first_inst.rs1;
        instruction_o[fusion_port].rs2 = fusion_first_inst.rs2;
        instruction_o[~fusion_port] = standard_inst;

        // if first instruction is AUIPC update pc_offset to compensate for using first-instruction-PC instead of AUIPC-PC
        if (fusion_first_inst.use_imm && fusion_first_inst.use_pc) begin
            instruction_o[fusion_port].use_pc = fusion_first_inst.use_pc;
            if (fusion_first_inst.is_compressed) begin
                pc_offset = 3'b010;
            end else begin
                pc_offset = 3'b100;
            end
        end

        // Immediate from ADDI or AUIPC is summed with LOAD or ADDI immediate and pc_offset
        if (fusion_first_inst.use_imm) begin
            instruction_o[fusion_port].result = $signed($signed(fusion_first_inst.result[32:0]) + $signed(fusion_second_inst.result[32:0]) - pc_offset);
        end

        // The two is_compressed fields are encoded inside is_fusion
        case ({fusion_first_inst.is_compressed, fusion_second_inst.is_compressed})
            2'b11:
                instruction_o[fusion_port].is_fusion = 2'b01; 
            2'b01, 2'b10:
                instruction_o[fusion_port].is_fusion = 2'b10; 
            2'b00:
                instruction_o[fusion_port].is_fusion = 2'b11; 
        endcase
    end
end

endmodule
