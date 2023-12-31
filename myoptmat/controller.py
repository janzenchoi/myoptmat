"""
 Title:         Controller
 Description:   Deals with calling the different components of the code
 Author:        Janzen Choi

"""

# Libraries
import torch, copy
import myoptmat.interface.converter as converter
import myoptmat.interface.progressor as progressor
import myoptmat.interface.reader as reader
import myoptmat.interface.recorder as recorder
import myoptmat.math.mapper as mapper
import myoptmat.math.general as general
import myoptmat.math.units as units
import myoptmat.models.__model__ as __model__

# Constants
NUM_POINTS = 50
HEADER_LIST = ["time", "strain", "stress", "temperature", "cycle"]

# Controller class
class Controller:
    
    # Constructor
    def __init__(self):
        
        # Initialise model variables
        self.model = None
        self.opt_model = None
        
        # Initialise optimisation variables
        self.algorithm = None
        self.loss_function = None
        self.objective_list = []
        
        # Initialise parameter variables
        self.param_dict = {}
        self.param_mapper_dict = {}
        self.initial_param_list = []
        
        # Initialise data variables
        self.data_mapper_dict = {}
        self.csv_dict_list = []
        self.raw_csv_dict_list = []
        self.data_bounds_dict = {}
        
        # Initialise transformed data variables
        self.dataset = None
        self.data = None
        self.results = None
        self.cycles = None
        self.types = None
        self.control = None
        
        # Initialise summary variables
        self.param_in_bound_list = []
        self.param_out_bound_list = []
        self.data_in_bound_list = []
        self.data_out_bound_list = []

        # Initialise result variables
        self.loss_value_list = []
        self.recorder = None
        self.record_interval = None

    # Defines the model
    def def_model(self, model_name:str):
        self.model = __model__.get_model(model_name)
        self.param_dict = self.model.get_param_dict()
    
    # Define parameter mappers
    def define_param_mappers(self, param_scale_dict:dict) -> None:
        
        # Iterate through parameters
        for param_name in self.param_dict.keys():
            
            # Define bounds based on whether the user has defined bounds or not
            is_defined = param_name in param_scale_dict.keys()
            in_l_bound = self.param_dict[param_name]["l_bound"]
            in_u_bound = self.param_dict[param_name]["u_bound"]
            out_l_bound = param_scale_dict[param_name]["l_bound"] if is_defined else in_l_bound
            out_u_bound = param_scale_dict[param_name]["u_bound"] if is_defined else in_u_bound
            
            # Create parameter mapper and add
            param_mapper = mapper.Mapper(in_l_bound, in_u_bound, out_l_bound, out_u_bound)
            self.param_mapper_dict[param_name] = param_mapper

        # Pass mapper dictionary to model
        self.model.define_param_mapper_dict(self.param_mapper_dict)
    
    # Define dictionary of initial values
    def define_initial_values(self, initial_param_dict:dict) -> None:
        for param_name in self.param_dict.keys():
            if param_name in initial_param_dict.keys():
                initial_value = initial_param_dict[param_name]
                initial_value = self.param_mapper_dict[param_name].map(initial_value)
            else:
                initial_value = self.param_mapper_dict[param_name].random()
            self.initial_param_list.append(initial_value)
    
    # Reads the CSV files as a list of dictionaries
    def load_csv_files(self, csv_file_list:list) -> None:
        
        # Load CSV data
        for csv_file in csv_file_list:
            csv_dict = converter.csv_to_dict(csv_file)
            self.csv_dict_list.append(csv_dict)
            
        # Checks and process dictionaries
        [converter.check_dict(data_dict) for data_dict in self.csv_dict_list]
        self.csv_dict_list = [converter.process_dict(data_dict, NUM_POINTS) for data_dict in self.csv_dict_list]
        self.raw_csv_dict_list = copy.deepcopy(self.csv_dict_list) # make a copy
        
        # Define bounds for each header
        for header in HEADER_LIST:
            data_list = [csv_dict[header] for csv_dict in self.csv_dict_list]
            data_list = [item for sublist in data_list for item in sublist]
            self.data_bounds_dict[header] = {"l_bound": min(data_list), "u_bound": max(data_list)}
    
    # Define data mappers
    def define_data_mappers(self, data_scale_dict:dict=None) -> None:

        # Iterate through data headers
        for header in HEADER_LIST:
            
            # Define bounds based on whether the user has defined bounds or not
            is_defined = header in data_scale_dict.keys()
            in_l_bound = self.data_bounds_dict[header]["l_bound"]
            in_u_bound = self.data_bounds_dict[header]["u_bound"]
            out_l_bound = data_scale_dict[header]["l_bound"] if is_defined else in_l_bound
            out_u_bound = data_scale_dict[header]["u_bound"] if is_defined else in_u_bound

            # Create data mapper and add
            data_mapper = mapper.Mapper(in_l_bound, in_u_bound, out_l_bound, out_u_bound)
            self.data_mapper_dict[header] = data_mapper
    
    # Scale the data
    def scale_and_process_data(self) -> None:
        for csv_dict in self.csv_dict_list:
            for header in HEADER_LIST:
                csv_dict[header] = self.data_mapper_dict[header].map(csv_dict[header])
        self.dataset = converter.dict_list_to_dataset(self.csv_dict_list, 1, NUM_POINTS)
        self.data, self.results, self.cycles, self.types, self.control = reader.load_dataset(self.dataset)
    
    # Defines the objectives
    def define_objectives(self) -> float:
        self.loss_function = torch.nn.MSELoss(reduction="sum")
    
    # Gets the objective values
    def get_objective_values(self) -> float:
        pass
    
    # Defines the optimiser
    def define_algorithm(self, algorithm_name:str="adam") -> None:
        self.opt_model = self.model.get_opt_model(self.initial_param_list, NUM_POINTS//2)
        params = self.opt_model.parameters()
        if algorithm_name == "adam":
            self.algorithm = torch.optim.Adam(params)
        elif algorithm_name == "lbfgs":
            self.algorithm = torch.optim.LBFGS(params)
        elif algorithm_name == "lbfgsl": # i.e., LBFGS with line search
            self.algorithm = torch.optim.LBFGS(params, line_search_fn="strong_wolfe")
    
    # Prepares the summary information
    def prepare_summary(self):
    
        # Get bound / scale summary for parameters
        for param_name in self.param_dict.keys():
            param_mapper = self.param_mapper_dict[param_name]
            in_l_bound, in_u_bound = param_mapper.get_in_bounds()
            self.param_in_bound_list.append("[{:0.3}, {:0.3}]".format(float(in_l_bound), float(in_u_bound)))
            out_l_bound, out_u_bound = param_mapper.get_out_bounds()
            self.param_out_bound_list.append("[{:0.3}, {:0.3}]".format(float(out_l_bound), float(out_u_bound)))
    
        # Get scale summary for data
        for header in HEADER_LIST:
            data_mapper = self.data_mapper_dict[header]
            in_l_bound, in_u_bound = data_mapper.get_in_bounds()
            self.data_in_bound_list.append("[{:0.3}, {:0.3}]".format(float(in_l_bound), float(in_u_bound)))
            out_l_bound, out_u_bound = data_mapper.get_out_bounds()
            self.data_out_bound_list.append("[{:0.3}, {:0.3}]".format(float(out_l_bound), float(out_u_bound)))
    
    # Gets the optimal prediction
    # TODO - use torch.transpose(prediction, 0, 1)[0] to allow different input types
    def get_prediction(self) -> torch.tensor:
        prediction = self.opt_model(self.data, self.cycles, self.types, self.control)
        prediction_mapper = self.data_mapper_dict["stress"]
        prediction = prediction_mapper.map(prediction)
        return prediction
    
    # Calculates the prediction discrepancy    
    def closure(self) -> float:
        self.algorithm.zero_grad()
        prediction = self.get_prediction()
        lossv = self.loss_function(prediction, self.results)
        lossv.backward()
        return lossv

    # Initialises the recorder
    def initialise_recorder(self, record_path:str, record_interval:int) -> None:
        self.recorder = recorder.Recorder(record_path)
        self.record_interval = record_interval
    
    # Get current unscaled optimal parameters
    def get_opt_params(self) -> list:
        opt_param_list = []
        for param_name in self.param_dict.keys():
            scaled_param = float(getattr(self.opt_model, param_name).data)
            param_mapper = self.param_mapper_dict[param_name]
            unscaled_param = param_mapper.unmap(scaled_param)
            opt_param_list.append(unscaled_param)
        return opt_param_list
    
    # # Gets experimental and predicted data
    # def get_exp_prd_data(self, x_label:str, y_label:str) -> dict:
        
    #     # Gets the unmapped (y) prediction
    #     prediction = self.get_prediction()
    #     prediction = self.data_mapper_dict[y_label].unmap(prediction)
        
    
    # Get flattened experimental and predicted data (based on optimal parameters)
    def get_exp_prd_data(self, x_label:str, y_label:str) -> tuple:
        
        # Get prediction
        prediction = self.get_prediction()
        prediction = self.data_mapper_dict[y_label].unmap(prediction)

        # Get experimental and predicted data
        exp_x_list, exp_y_list, prd_y_list = [], [], []
        for i in range(len(self.raw_csv_dict_list)):
            exp_x_list += self.raw_csv_dict_list[i][x_label]
            exp_y_list += self.raw_csv_dict_list[i][y_label]
            prd_y_list += [p[i] for p in prediction.tolist()]
        
        # Return data
        return exp_x_list, exp_y_list, prd_y_list

    # Conducts the optimisation
    def optimise(self, iterations:int=5, update_interval:int=1) -> None:
        
        # Initialise optimisation
        general.print_value_list("Optimisation:", end="")
        pv = progressor.ProgressVisualiser(iterations, pretext="loss=?, ")
        for curr_iteration in range(1, iterations+1):
            
            # Take a step, add loss to history, and print loss
            closure_loss = self.algorithm.step(self.closure)
            loss_value = float(closure_loss.detach().cpu().numpy())
            self.loss_value_list.append(float(loss_value))
            
            # Display every defined interval
            loss_string = "{:0.2}".format(closure_loss.detach().cpu().numpy())
            display = curr_iteration % update_interval == 0
            pv.progress(pretext=f"loss={loss_string}, ", display=display)
            
            # If recorder initialised and iterations reached, then record results
            if self.recorder != None and curr_iteration % self.record_interval == 0:
                self.record_results(iterations, curr_iteration)
        
        # End optimisation
        opt_params = self.get_opt_params()
        general.print_value_list("Final Params:", opt_params)
        pv.end()

    # Runs each step of the optimisation
    def record_results(self, iterations:int, curr_iteration:int) -> None:
        
        # Initialise
        curr_iteration = str(curr_iteration).zfill(len(str(iterations)))
        self.recorder.create_new_file(curr_iteration)
        x_label, y_label = "strain", "stress"

        # Write the parameter and data summary
        self.recorder.write_data({
            "data":         HEADER_LIST,
            "d. bounds":       self.data_in_bound_list,
            "d. scales":       self.data_out_bound_list,
            "|":               ["|"] * len(self.param_dict.keys()),
            "parameter":       list(self.param_dict.keys()),
            "p. bounds":       self.param_in_bound_list,
            "p. scales":       self.param_out_bound_list,
            "p. optimised":    self.get_opt_params(),
        }, "summary")
        
        # Plot experimental and predicted data
        exp_x_list, exp_y_list, prd_y_list = self.get_exp_prd_data(x_label, y_label)
        self.recorder.write_plot({
            "experimental": {"x": exp_x_list, "y": exp_y_list, "size": 5},
            "predicted":    {"x": exp_x_list, "y": prd_y_list, "size": 3}
        }, "plot", units.MYOPTMAT_UNITS[x_label], units.MYOPTMAT_UNITS[y_label], "scatter")
        
        # Plots the loss history
        loss_x_list = list(range(1, len(self.loss_value_list)+1))
        thin_indexes = general.get_thin_indexes(len(self.loss_value_list), NUM_POINTS)
        self.recorder.write_plot({
            "loss history": {
                "x": [loss_x_list[i] for i in thin_indexes],
                "y": [self.loss_value_list[i] for i in thin_indexes],
                "size": 3
            }
        }, "loss", "iteration", "loss", "line")
        
        # Saves the file
        self.recorder.close()
    
    # Displays the initial parameters and initial gradient
    def display_initial_information(self):
        
        # Display initial parameters
        initial_unscaled_param_list = []
        for i in range(len(self.param_dict.keys())):
            param_name = list(self.param_dict.keys())[i]
            param_mapper = self.param_mapper_dict[param_name]
            unscaled_param = param_mapper.unmap(self.initial_param_list[i])
            initial_unscaled_param_list.append(unscaled_param)
        general.print_value_list("Initial Params:", initial_unscaled_param_list)
        
        # Print initial gradient
        self.closure()
        gradients = [getattr(self.opt_model, param_name).grad for param_name in self.param_dict.keys()]
        gradients = [abs(g) for g in gradients]
        general.print_value_list("Initial Gradient:", gradients)
