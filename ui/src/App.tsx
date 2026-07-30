// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Main App component for the Shopping Assistant
 */

import React, { useState } from "react";
import { ToastContainer } from "react-toastify";
import "react-toastify/dist/ReactToastify.css";

import Navbar from "./components/Navbar";
import Apparel from "./components/Apparel";
import Chatbox from "./components/chatbox/chatbox";
import Footer from "./components/Footer";

const App: React.FC = () => {
  const [newRenderImage, setNewRenderImage] = useState<string>("");
  const [retrievedProducts, setRetrievedProducts] = useState<any[]>([]);
  const [isCartView, setIsCartView] = useState<boolean>(false);
  const chatTriggerRef = React.useRef<((msg: string) => void) | null>(null);

  const handleRemoveProduct = (productName: string) => {
    if (chatTriggerRef.current) {
      chatTriggerRef.current(`remove ${productName} from cart`);
    }
  };

  return (
    <div className="bg-[#FFFFFF] flex flex-col h-screen w-screen">
      <Navbar />
      <Apparel 
        newRenderImage={newRenderImage} 
        retrievedProducts={retrievedProducts} 
        isCartView={isCartView}
        onRemoveProduct={handleRemoveProduct}
      />
      <Chatbox 
        setNewRenderImage={setNewRenderImage} 
        setRetrievedProducts={setRetrievedProducts} 
        isCartView={isCartView}
        setIsCartView={setIsCartView}
        chatTriggerRef={chatTriggerRef}
      />
      <Footer />
      <ToastContainer position="top-right" />
    </div>
  );
};

export default App;
